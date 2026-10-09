"""Main window: sidebar, library / albums / artists / lyrics pages, queue drawer, player bar."""

import os
import random
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QByteArray, QEvent, QItemSelectionModel, QObject, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QComboBox, QDialog, QFileDialog,
                               QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox,
                               QPushButton, QSystemTrayIcon, QTableView,
                               QVBoxLayout, QWidget)

from .. import APP_NAME, APP_VERSION, audio, icons, library as libmod, meta, paths, theme, updater, winutil
from ..collection import Collection
from ..i18n import songs as n_songs, tr
from ..settings import read_json, write_json_atomic
from .collection_view import AlbumPage, ArtistPage, CollectionPage
from .home_page import HomePage
from .decor import BackdropStack, DecorBackground, MatrixRain
from .library_view import COL_NUM, COL_TITLE, LibraryPage
from .lyrics_page import LyricsPage
from .mini_player import MiniPlayer
from .player_bar import PlayerBar
from .queue_panel import QueuePanel
from .settings_dialog import SettingsDialog
from .widgets import BrandLabel, IconButton, Toast, fmt_time

NAV_ITEMS = (
    ("home", "Home", "home", "Your top artists, most played songs and the theme"),
    ("songs", "Songs", "songs", "Every song in your library"),
    ("albums", "Albums", "album", "Your albums, made from the songs' tags"),
    ("artists", "Artists", "artist", "Everyone you listen to"),
    ("favorites", "Favorites", "heart", "Songs you marked with the heart"),
    ("recent", "Recently added", "clock", "Songs added to the library most recently"),
    ("most", "Most played", "fire", "Songs you play the most"),
    ("history", "Recently played", "sync", "Songs you played lately"),
)


class _Bridge(QObject):
    """Carries results from worker threads into the Qt thread."""
    scan_progress = Signal(int, int)
    scan_done = Signal(dict)
    lyrics_ready = Signal(str, object)
    files_ready = Signal(list, str)          # tracks, "replace" | "append" | "append_quiet"
    update_checked = Signal(object, bool)    # (version, path or url, size) or None, manual check?
    update_progress = Signal(int, int)       # downloaded bytes, total
    update_downloaded = Signal(object)       # installer path, or the error


class Sidebar(DecorBackground):
    """Sidebar background with the theme's decoration under the playlists."""

    def __init__(self, parent=None):
        super().__init__(parent, area=(0.5, 0.93))

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.drawLine(self.width() - 1, 0, self.width() - 1, self.height())


class MainWindow(QMainWindow):
    def __init__(self, settings, library, player, covers):
        super().__init__()
        self.settings = settings
        self.library = library
        self.player = player
        self.covers = covers
        self.bridge = _Bridge()
        self._lyrics_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="T9Lyrics")
        self._files_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="T9Files")
        self._current_lyrics = None
        self._lyrics_path = None
        self._settings_dialog = None
        self._mini = None
        self._quitting = False
        self._tray = None
        self._view_key = ("songs",)
        self._history = []
        self._collection = None
        self._was_maximized = False
        self._current_cover = None
        self._current_blur = None
        self._restart_playing = False
        self.covers.overrides = dict(settings["album_covers"])
        self.covers.artist_overrides = dict(settings["artist_pictures"])
        self.covers.online.enabled = settings["online_covers"]
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(980, 620)
        self.setAcceptDrops(True)
        self._build()
        self._connect()
        self._apply_lyrics_style()
        self._set_density(settings["list_density"], save=False)
        self._restore_geometry()
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(33)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start()
        self._session_timer = QTimer(self)
        self._session_timer.setInterval(15000)
        self._session_timer.timeout.connect(self.save_session)
        self._session_timer.start()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(700)
        self._refresh_timer.timeout.connect(self.refresh_view)
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.setInterval(2800)
        self._idle_timer.timeout.connect(self._hide_bar_idle)
        self._setup_tray()

    # ================================================================== building
    def _build(self):
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        outer.addLayout(body, 1)

        self.sidebar = self._build_sidebar()
        body.addWidget(self.sidebar)

        is_playing = lambda: self.player.state == audio.STATE_PLAYING  # noqa: E731
        self.stack = BackdropStack()
        self.library_page = LibraryPage(self.covers, is_playing)
        self.lyrics_page = LyricsPage()
        self.lyrics_page.set_rain(self.settings["matrix_rain"])
        self.welcome = self._build_welcome()
        self.home_page = HomePage(self.covers, is_playing)
        self.albums_page = CollectionPage(self.covers, "albums")
        self.artists_page = CollectionPage(self.covers, "artists")
        self.album_page = AlbumPage(self.covers, is_playing)
        self.artist_page = ArtistPage(self.covers, is_playing)
        for page in (self.home_page, self.library_page, self.lyrics_page, self.welcome, self.albums_page,
                     self.artists_page, self.album_page, self.artist_page):
            self.stack.addWidget(page)
        body.addWidget(self.stack, 1)

        self.queue_panel = QueuePanel()
        self.queue_panel.hide()
        body.addWidget(self.queue_panel)

        self.bar = PlayerBar(self.player)
        outer.addWidget(self.bar)
        self.toast = Toast(root)
        root.toast_bottom_margin = lambda: (self.bar.height() if self.bar.isVisible() else 0) + 24

        self.lyrics_page.view.set_sources(self._lyrics_position, is_playing)

    def _build_sidebar(self):
        side = Sidebar()
        side.setFixedWidth(232)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(0, 14, 0, 12)
        lay.setSpacing(2)
        brand = QHBoxLayout()
        brand.setContentsMargins(18, 4, 12, 12)
        brand.addWidget(BrandLabel(height=30))
        brand.addStretch(1)
        lay.addLayout(brand)

        header = QLabel(tr("LIBRARY"))
        header.setObjectName("NavHeader")
        lay.addWidget(header)
        self.nav = QListWidget()
        self.nav.setObjectName("Nav")
        self.nav.setIconSize(QSize(18, 18))
        self.nav.setFixedHeight(len(NAV_ITEMS) * 38 + 6)
        self.nav.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        for key, label, icon_name, tip in NAV_ITEMS:
            item = QListWidgetItem(icons.icon(icon_name, theme.DIM, 18), tr(label))
            item.setData(Qt.UserRole, key)
            item.setToolTip(tr(tip))
            self.nav.addItem(item)
        lay.addWidget(self.nav)

        ph = QHBoxLayout()
        ph.setContentsMargins(0, 0, 10, 0)
        header2 = QLabel(tr("PLAYLISTS"))
        header2.setObjectName("NavHeader")
        ph.addWidget(header2)
        ph.addStretch(1)
        self.add_playlist_btn = IconButton("add", tr("New playlist or import an .m3u file"), 26, 16)
        ph.addWidget(self.add_playlist_btn, 0, Qt.AlignBottom)
        lay.addLayout(ph)
        self.playlists = QListWidget()
        self.playlists.setObjectName("Nav")
        self.playlists.setIconSize(QSize(16, 16))
        self.playlists.setContextMenuPolicy(Qt.CustomContextMenu)
        self.playlists.setToolTip(tr("Right-click a playlist for more options"))
        lay.addWidget(self.playlists, 1)

        self.scan_label = QLabel("")
        self.scan_label.setObjectName("Dim")
        self.scan_label.setStyleSheet("font-size: 11px; padding: 0 16px;")
        self.scan_label.setWordWrap(True)
        self.scan_label.hide()
        lay.addWidget(self.scan_label)
        bottom = QHBoxLayout()
        bottom.setContentsMargins(12, 6, 12, 0)
        self.add_music_btn = QPushButton("  " + tr("Add music"))
        self.add_music_btn.setIcon(icons.icon("folder", theme.TEXT, 16))
        self.add_music_btn.setToolTip(tr("Add a folder with music to the library"))
        self.add_music_btn.setCursor(Qt.PointingHandCursor)
        self.open_btn = IconButton("note", tr("Open audio files without adding them (Ctrl+O)"), 34, 18)
        self.settings_btn = IconButton("settings", tr("Settings"), 34, 20)
        bottom.addWidget(self.add_music_btn, 1)
        bottom.addWidget(self.open_btn)
        bottom.addWidget(self.settings_btn)
        lay.addLayout(bottom)
        return side

    def _build_welcome(self):
        w = QWidget()
        self._welcome_rain = None
        if theme.DECOR == "rain":
            rain = MatrixRain(w, density=0.5)
            rain.setVisible(self.settings["matrix_rain"])
            w.resizeEvent = lambda e, r=rain, ww=w: r.setGeometry(ww.rect())
            self._welcome_rain = rain
        lay = QVBoxLayout(w)
        lay.addStretch(2)
        brand_row = QHBoxLayout()
        brand_row.addStretch(1)
        if theme.BRAND == "cat":
            brand_row.addWidget(BrandLabel(height=150, text_size=64, spacing=22))
        else:
            brand_row.addWidget(BrandLabel(height=78, text_size=46, spacing=18))
        brand_row.addStretch(1)
        lay.addLayout(brand_row)
        lay.addSpacing(18)
        title = QLabel(theme.title_text(tr("Welcome")))
        title.setObjectName("H1")
        title.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)
        sub = QLabel(tr("Lossless playback, synced lyrics and a fast library.") + "\n" +
                     tr("Add the folder where you keep your music to get started."))
        sub.setObjectName("Dim")
        sub.setAlignment(Qt.AlignCenter)
        lay.addWidget(sub)
        lay.addSpacing(16)
        row = QHBoxLayout()
        row.addStretch(1)
        add = QPushButton("  " + tr("Add music folder"))
        add.setObjectName("Primary")
        add.setIcon(icons.icon("folder", theme.ON_ACCENT, 16))
        add.setToolTip(tr("Choose the folder with your music"))
        add.setCursor(Qt.PointingHandCursor)
        add.clicked.connect(self.add_music_folder)
        opn = QPushButton("  " + tr("Open files"))
        opn.setIcon(icons.icon("note", theme.TEXT, 16))
        opn.setToolTip(tr("Just play some files without adding a folder"))
        opn.setCursor(Qt.PointingHandCursor)
        opn.clicked.connect(self.open_files)
        row.addWidget(add)
        row.addWidget(opn)
        row.addStretch(1)
        lay.addLayout(row)
        hint = QLabel(tr("Tip: you can also drag & drop songs or folders onto this window."))
        hint.setStyleSheet(f"color: {theme.FAINT}; font-size: 11px;")
        hint.setAlignment(Qt.AlignCenter)
        lay.addSpacing(10)
        lay.addWidget(hint)
        lay.addStretch(3)
        return w

    def _connect(self):
        p = self.player
        self.nav.currentItemChanged.connect(self._on_nav)
        self.playlists.currentItemChanged.connect(self._on_playlist_selected)
        self.playlists.customContextMenuRequested.connect(self._playlist_menu)
        self.add_playlist_btn.clicked.connect(self._playlist_add_menu)
        self.add_music_btn.clicked.connect(self.add_music_folder)
        self.open_btn.clicked.connect(self.open_files)
        self.settings_btn.clicked.connect(self.open_settings)
        lp = self.library_page
        lp.play_requested.connect(self._play_from_list)
        lp.shuffle_requested.connect(self._shuffle_list)
        lp.table.play_clicked.connect(lambda row: self._play_toggle(lp.table.model_.tracks(), row))
        lp.table.context_requested.connect(lambda pos: self._track_menu(lp.table, pos))
        lp.sort_chosen.connect(self._on_sort_chosen)
        lp.density_chosen.connect(self._set_density)
        lp.reorder_requested.connect(self._on_reorder)
        for grid_page in (self.albums_page, self.artists_page):
            grid_page.grid.open_item.connect(self._open_item)
            grid_page.grid.play_item.connect(lambda item: self.player.play_tracks(item.tracks, 0))
            grid_page.grid.item_menu.connect(self._tile_menu)
        for page in (self.album_page, self.artist_page):
            page.back_requested.connect(self.go_back)
            page.play_tracks.connect(self._play_from_list)
            page.play_toggle.connect(self._play_toggle)
            page.shuffle_tracks.connect(self._shuffle_list)
            page.open_album.connect(self.show_album)
            page.open_artist.connect(self.show_artist_named)
            page.track_menu.connect(self._track_menu)
            page.item_menu.connect(self._tile_menu)
        self.album_page.more_menu.connect(self._album_menu)
        hp = self.home_page
        hp.play_tracks.connect(self._play_from_list)
        hp.play_toggle.connect(self._play_toggle)
        hp.shuffle_tracks.connect(self._shuffle_list)
        hp.open_item.connect(self._open_item)
        hp.play_item.connect(lambda item: self.player.play_tracks(item.tracks, 0))
        hp.item_menu.connect(self._tile_menu)
        hp.track_menu.connect(self._track_menu)
        hp.show_view.connect(self._nav_to)
        self.artist_page.more_menu.connect(self._artist_menu)
        self.bar.lyrics_clicked.connect(self.toggle_lyrics)
        self.bar.cover_clicked.connect(self.toggle_lyrics)
        self.bar.queue_clicked.connect(self.toggle_queue)
        self.bar.mini_clicked.connect(self.show_mini)
        self.bar.title_clicked.connect(self._show_current_album)
        self.bar.artist_clicked.connect(self._show_current_artist)
        self.bar.sleep_clicked.connect(self._sleep_menu)
        lyr = self.lyrics_page
        lyr.back_requested.connect(self.leave_lyrics)
        lyr.fullscreen_requested.connect(self.toggle_fullscreen)
        lyr.font_step.connect(self.change_lyrics_size)
        lyr.offset_step.connect(self.change_lyrics_offset)
        lyr.swap_requested.connect(self._swap_cover_side)
        lyr.view.seek_requested.connect(p.seek)
        self.queue_panel.jump_requested.connect(p.jump_to)
        self.queue_panel.remove_requested.connect(p.remove_from_queue)
        self.queue_panel.clear_requested.connect(p.clear_upcoming)
        p.track_changed.connect(self._on_track_changed)
        p.queue_changed.connect(self._on_queue_changed)
        p.state_changed.connect(self._on_state_changed)
        p.message.connect(lambda level, text: self.toast.show_message(text, level))
        p.favorite_changed.connect(self._on_favorite_changed)
        p.play_counted.connect(self._on_play_counted)
        self.covers.cover_ready.connect(self._on_cover)
        self.bridge.scan_progress.connect(self._on_scan_progress)
        self.bridge.scan_done.connect(self._on_scan_done)
        self.bridge.lyrics_ready.connect(self._on_lyrics_ready)
        self.bridge.files_ready.connect(self._play_track_list)
        self.bridge.update_checked.connect(self._on_update_checked)
        self.bridge.update_progress.connect(self._on_update_progress)
        self.bridge.update_downloaded.connect(self._on_update_downloaded)

    # ================================================================== startup
    def start(self, files=None):
        """Called once the window is visible: load library, restore session."""
        self.library.load()
        self.reload_playlists()
        self._nav_to("home")
        if files:
            self.play_files(files)
        elif self.settings["resume_on_start"] or os.environ.get("T9_RESUME_PLAYING"):
            self.restore_session()
        if self.settings["rescan_on_start"] and self.settings["library_folders"]:
            QTimer.singleShot(1500, self.rescan)
        if (getattr(self, "fresh_install", False) or os.environ.get("T9_SHOW_TOUR")) and not self.settings["tour_done"]:
            QTimer.singleShot(900, self.show_tour)
        last = self.settings["last_run_version"]
        if last != APP_VERSION:
            self.settings.set("last_run_version", APP_VERSION)
            if last and updater.parse_version(last) < updater.parse_version(APP_VERSION):
                QTimer.singleShot(1200, lambda: self.toast.show_message(
                    tr("Updated to version {version}", version=APP_VERSION) + " ✨", ms=6000))
        if self.settings["update_folder"] or self.settings["online_updates"]:
            QTimer.singleShot(4000, lambda: self.check_for_update(manual=False))
        self._update_welcome()
        if theme.extra("welcome_toast"):
            QTimer.singleShot(900, lambda: self.toast.show_message(tr(theme.extra("welcome_toast")) + " ♥"))

    def _update_welcome(self):
        if self.stack.currentWidget() not in (self.library_page, self.home_page, self.welcome):
            return
        empty = not self.settings["library_folders"] and not self.library.library_tracks()
        on_start = self._view_key in (("songs",), ("home",))
        self.stack.setCurrentWidget(self.welcome if (empty and on_start) else self._page_for_view())

    def _nav_to(self, key):
        """Select a LIBRARY entry in the sidebar by its key ("home", "songs", ...)."""
        for row in range(self.nav.count()):
            if self.nav.item(row).data(Qt.UserRole) == key:
                if self.nav.currentRow() == row:
                    self._on_nav(self.nav.item(row))
                else:
                    self.nav.setCurrentRow(row)
                return

    def show_tour(self):
        """First-run tour (only after a fresh install; skippable)."""
        from .tour import TourOverlay
        steps = [
            (None, tr("Hey, welcome to Triple 9!"),
             tr("I'll show you around in 30 seconds. Lossless music, synced lyrics and themes inspired by "
                "Juice WRLD's albums - 999.")),
            (self.add_music_btn, tr("Add your music"),
             tr("Choose the folder with your songs. The player reads the tags, album covers and lyrics by itself.")),
            (self.nav, tr("Your library"),
             tr("Home shows your top artists and most played songs. Songs, Albums and Artists are all here too.")),
            (self.bar.lyrics_btn, tr("Synced lyrics"),
             tr("Click here (or press L) to see the lyrics move with the song. Click a line to jump there.")),
            (self.bar.mini_btn, tr("Compact player"),
             tr("A small window that stays on top while you do other things (Ctrl+M).")),
            (self.settings_btn, tr("Themes and settings"),
             tr("Pick a theme inspired by his albums, change the language, turn on bit-perfect playback...")),
            (None, tr("That's it - enjoy!"),
             tr("Turn every negative into a positive. 999 forever.")),
        ]
        self.settings.set("tour_done", True)
        self._tour = TourOverlay(self, steps)
        self._tour.show()
        self._tour.raise_()
        self._tour.setFocus()

    def collection(self):
        if self._collection is None:
            self._collection = Collection(self.library.library_tracks())
        return self._collection

    # ================================================================== views
    def _on_nav(self, item, _prev=None):
        if item is None:
            return
        self.playlists.blockSignals(True)
        self.playlists.clearSelection()
        self.playlists.setCurrentRow(-1)
        self.playlists.blockSignals(False)
        self._history.clear()
        self._view_key = (item.data(Qt.UserRole),)
        self.refresh_view()
        self._show_view_page()

    def _on_playlist_selected(self, item, _prev=None):
        if item is None:
            return
        self.nav.blockSignals(True)
        self.nav.clearSelection()
        self.nav.setCurrentRow(-1)
        self.nav.blockSignals(False)
        self._history.clear()
        self._view_key = ("playlist", item.data(Qt.UserRole))
        self.refresh_view()
        self._show_view_page()

    def _page_for_view(self):
        kind = self._view_key[0]
        return {"home": self.home_page, "albums": self.albums_page, "artists": self.artists_page,
                "album": self.album_page, "artist": self.artist_page}.get(kind, self.library_page)

    def _show_view_page(self):
        if self.isFullScreen():
            self.toggle_fullscreen()
        self.sidebar.show()
        self.bar.lyrics_btn.setChecked(False)
        page = self._page_for_view()
        self.stack.setCurrentWidget(page)
        if page in (self.library_page, self.home_page):
            self._update_welcome()

    def refresh_view(self):
        key = self._view_key
        kind = key[0]
        if kind == "home":
            self._collection = None
            self.home_page.set_data(self.library.library_tracks(), self.collection())
            return
        if kind in ("albums", "artists"):
            self._collection = None
            (self.albums_page if kind == "albums" else self.artists_page).set_collection(self.collection())
            return
        if kind == "album":
            self._collection = None
            album = self.collection().albums.get(key[1])
            if album is not None:
                self.album_page.show_album(album, self.collection())
            return
        if kind == "artist":
            self._collection = None
            artist = self.collection().artists.get(key[1])
            if artist is not None:
                self.artist_page.show_artist(artist)
            return
        tracks = self.library.library_tracks()
        sort = None
        empty = ""
        if kind == "songs":
            title = tr("Songs")
            sort = (COL_TITLE, Qt.AscendingOrder)
            empty = tr("Your library is empty.") + "\n" + tr("Click “Add music” to choose your music folder.")
        elif kind == "favorites":
            title = tr("Favorites")
            tracks = sorted((t for t in self.library.tracks.copy().values() if t.favorite),
                            key=lambda t: t.title.casefold())
            sort = (COL_NUM, Qt.AscendingOrder)
            empty = tr("No favorites yet.") + "\n" + tr("Click the heart next to a song to add it here.")
        elif kind == "recent":
            title = tr("Recently added")
            tracks = sorted(tracks, key=lambda t: t.added, reverse=True)[:500]
            sort = (COL_NUM, Qt.AscendingOrder)
        elif kind == "most":
            title = tr("Most played")
            tracks = sorted((t for t in tracks if t.plays > 0), key=lambda t: t.plays, reverse=True)[:300]
            sort = (COL_NUM, Qt.AscendingOrder)
            empty = tr("Play some music and your top songs will show up here.")
        elif kind == "history":
            title = tr("Recently played")
            tracks = sorted((t for t in self.library.tracks.copy().values() if t.last_played > 0),
                            key=lambda t: t.last_played, reverse=True)[:300]
            sort = (COL_NUM, Qt.AscendingOrder)
            empty = tr("Songs you play will be listed here.")
        elif kind == "playlist":
            name = next((n for pid, n in self.library.playlists() if pid == key[1]), tr("Playlist"))
            title = name
            tracks = self.library.playlist_tracks(key[1])
            sort = (COL_NUM, Qt.AscendingOrder)
            empty = tr("This playlist is empty.") + "\n" + tr("Right-click songs → Add to playlist.")
        else:
            return
        new_view = self.library_page.view_key != key
        self.library_page.set_content(key, theme.title_text(title), tracks, sort, empty, show_plays=kind == "most")
        if new_view:
            saved = self.settings["list_sort"].get(self._sort_name(key))
            if saved:
                self.library_page.apply_sort_key(saved)
        self.library_page.table.model_.set_playing(self.player.current.path if self.player.current else None)

    @staticmethod
    def _sort_name(key):
        return f"playlist:{key[1]}" if key[0] == "playlist" else key[0]

    def _on_sort_chosen(self, key, option):
        if not key:
            return
        sorts = dict(self.settings["list_sort"])
        sorts[self._sort_name(key)] = option
        self.settings.set("list_sort", sorts)

    def _set_density(self, density, save=True):
        for table in self._tables():
            table.set_compact(density == "compact")
        if save:
            self.settings.set("list_density", density)

    def _on_reorder(self, key, rows, drop_row):
        """Songs dragged inside a playlist (custom order)."""
        if not key or key[0] != "playlist" or not rows:
            return
        model = self.library_page.table.model_
        source = [t.path for t in model.source_tracks()]
        moving = [model.list_position(r) for r in rows if model.list_position(r) >= 0]
        if not moving:
            return
        insert_at = model.list_position(drop_row) if drop_row < model.rowCount() else len(source)
        insert_at -= sum(1 for i in moving if i < insert_at)
        picked = [source[i] for i in moving]
        rest = [p for i, p in enumerate(source) if i not in set(moving)]
        rest[insert_at:insert_at] = picked
        missing = [p for p in self.library.playlist_paths(key[1]) if p not in set(source)]
        self.library.set_playlist_paths(key[1], rest + missing)
        self.refresh_view()
        table = self.library_page.table
        table.clearSelection()
        for r in range(insert_at, insert_at + len(picked)):
            table.selectionModel().select(table.model_.index(r, 0),
                                          QItemSelectionModel.Select | QItemSelectionModel.Rows)

    def _push_history(self):
        if not self._history or self._history[-1] != self._view_key:
            self._history.append(self._view_key)
        del self._history[:-30]

    def go_back(self):
        if self._history:
            self._view_key = self._history.pop()
        else:
            self._view_key = ("albums",) if self._view_key[0] == "album" else ("artists",)
        self.refresh_view()
        self._show_view_page()

    def _open_item(self, item):
        if hasattr(item, "albums"):
            self.show_artist(item)
        else:
            self.show_album(item)

    def show_album(self, album):
        if album is None:
            return
        self._push_history()
        self._view_key = ("album", album.key)
        self.album_page.show_album(album, self.collection())
        self._show_view_page()

    def show_artist(self, artist):
        if artist is None:
            return
        self._push_history()
        self._view_key = ("artist", artist.key)
        self.artist_page.show_artist(artist)
        self._show_view_page()

    def show_artist_named(self, name):
        artist = self.collection().artist_named(name)
        if artist is None:
            self.toast.show_message(tr("No artist called “{name}” in the library", name=name), "warning")
            return
        self.show_artist(artist)

    def _show_current_album(self):
        t = self.player.current
        if t is None:
            return
        album = self.collection().album_of(t)
        if album is None:
            self.toast.show_message(tr("This song has no album in its tags"), "warning")
            return
        if self.stack.currentWidget() is self.lyrics_page:
            self.leave_lyrics()
        self.show_album(album)

    def _show_current_artist(self):
        t = self.player.current
        if t is None:
            return
        if self.stack.currentWidget() is self.lyrics_page:
            self.leave_lyrics()
        from ..collection import split_artists
        names = split_artists(t.artist or t.albumartist, t.title)
        if names:
            self.show_artist_named(names[0])

    def reload_playlists(self):
        current = self._view_key[1] if self._view_key[0] == "playlist" else None
        self.playlists.blockSignals(True)
        self.playlists.clear()
        for pid, name in self.library.playlists():
            item = QListWidgetItem(icons.icon("list", theme.DIM, 16), name)
            item.setData(Qt.UserRole, pid)
            self.playlists.addItem(item)
            if pid == current:
                self.playlists.setCurrentItem(item)
        self.playlists.blockSignals(False)

    # ================================================================== playback actions
    def _play_from_list(self, tracks, row):
        self.player.play_tracks(tracks, row)

    def _play_toggle(self, tracks, row):
        """The round button next to a song: first click plays it, next clicks pause / resume."""
        if not 0 <= row < len(tracks):
            return
        cur = self.player.current
        if cur is not None and cur.path == tracks[row].path and self.player.state != audio.STATE_STOPPED:
            self.player.play_pause()
        else:
            self.player.play_tracks(tracks, row)

    def _shuffle_list(self, tracks):
        if not tracks:
            return
        if not self.player.shuffle:
            self.player.set_shuffle(True)
        self.player.play_tracks(tracks, random.randrange(len(tracks)))

    def play_files(self, files, replace=True):
        """Play dropped / opened files. Unknown files have their tags read off the UI thread."""
        bridge = self.bridge
        library = self.library

        def job():
            paths_list = self._expand_paths(files)[:5000]
            tracks = []
            started = False
            for path in paths_list:
                try:
                    tracks.append(library.track_for_path(path))
                except Exception:
                    continue
                if not started:
                    # start the first song right away, the rest follows into the queue
                    started = True
                    bridge.files_ready.emit(list(tracks), "replace" if replace else "append")
                    tracks = []
                elif len(tracks) >= 200:
                    bridge.files_ready.emit(tracks, "append_quiet")
                    tracks = []
            if tracks or not started:
                bridge.files_ready.emit(tracks, "append_quiet" if started else "replace")

        unknown = [f for f in files if not self.library.get(os.path.normpath(f))]
        if len(unknown) > 20 or any(os.path.isdir(f) for f in files):
            self.toast.show_message(tr("Reading files..."), ms=1500)
        self._files_pool.submit(job)

    def _play_track_list(self, tracks, mode):
        if not tracks:
            if mode == "replace":
                self.toast.show_message(tr("No playable audio files found"), "warning")
            return
        if mode == "replace":
            self.player.play_tracks(tracks, 0)
        else:
            self.player.enqueue(tracks)

    @staticmethod
    def _expand_paths(items):
        out = []
        for item in items:
            item = os.path.normpath(item)
            if os.path.isdir(item):
                found = []
                for dirpath, dirnames, filenames in os.walk(item):
                    dirnames.sort(key=str.casefold)
                    for name in sorted(filenames, key=str.casefold):
                        if meta.is_audio(name):
                            found.append(os.path.join(dirpath, name))
                out.extend(found)
            elif item.lower().endswith((".m3u", ".m3u8")):
                out.extend(libmod.read_m3u(item))
            elif meta.is_audio(item) and os.path.isfile(item):
                out.append(item)
        return out

    def open_files(self):
        exts = " ".join(f"*{e}" for e in sorted(meta.AUDIO_EXTS))
        files, _ = QFileDialog.getOpenFileNames(
            self, tr("Open audio files"), self._last_dir(),
            f"{tr('Audio files')} ({exts});;{tr('Playlists')} (*.m3u *.m3u8);;{tr('All files')} (*.*)")
        if files:
            self.play_files(files)

    def _last_dir(self):
        folders = self.settings["library_folders"]
        return folders[0] if folders else paths.default_music_dir()

    # ================================================================== menus
    def _track_menu(self, table, pos):
        tracks = table.selected_tracks()
        if not tracks:
            row = table.rowAt(pos.y())
            if row < 0:
                return
            table.selectRow(row)
            tracks = table.selected_tracks()
        menu = QMenu(self)
        first = tracks[0]
        rows = table.selected_rows()
        in_playlist = self._view_key[0] == "playlist" and table is self.library_page.table
        menu.addAction(icons.icon("play", theme.TEXT, 16), tr("Play"),
                       lambda: self._play_from_list(table.model_.tracks(), rows[0]) if len(tracks) == 1
                       else self.player.play_tracks(tracks, 0))
        menu.addAction(icons.icon("next", theme.TEXT, 16), tr("Play next"), lambda: self._enqueue(tracks, True))
        menu.addAction(icons.icon("queue", theme.TEXT, 16), tr("Add to queue"), lambda: self._enqueue(tracks, False))
        self._add_playlist_submenu(menu, tracks)
        menu.addSeparator()
        fav_all = all(t.favorite for t in tracks)
        menu.addAction(icons.icon("heart" if not fav_all else "heart_outline", theme.RED_BRIGHT, 16),
                       tr("Remove from Favorites") if fav_all else tr("Add to Favorites"),
                       lambda: self._set_favorite(tracks, not fav_all))
        if in_playlist:
            menu.addAction(icons.icon("close", theme.TEXT, 16), tr("Remove from this playlist"),
                           lambda: self._remove_from_playlist(self._view_key[1], rows))
            if len(rows) == 1 and table.model_.sort_state() == (COL_NUM, Qt.AscendingOrder):
                menu.addAction(tr("Move up"), lambda: self._move_in_playlist(self._view_key[1], rows[0], -1))
                menu.addAction(tr("Move down"), lambda: self._move_in_playlist(self._view_key[1], rows[0], 1))
        menu.addSeparator()
        from ..collection import split_artists
        for name in split_artists(first.artist or first.albumartist, first.title)[:3]:
            menu.addAction(icons.icon("artist", theme.TEXT, 16), tr("Go to artist: {name}", name=name),
                           lambda n=name: self.show_artist_named(n))
        album = self.collection().album_of(first) if first.album else None
        if album is not None:
            menu.addAction(icons.icon("album", theme.TEXT, 16), tr("Go to album: {album}", album=album.title),
                           lambda: self.show_album(album))
        menu.addAction(icons.icon("folder", theme.TEXT, 16), tr("Show in folder"), lambda: self._show_in_folder(first.path))
        menu.addAction(icons.icon("more", theme.TEXT, 16), tr("Details..."), lambda: self.show_details(first))
        menu.exec(table.viewport().mapToGlobal(pos))

    def _add_playlist_submenu(self, menu, tracks):
        sub = menu.addMenu(icons.icon("playlist", theme.TEXT, 16), tr("Add to playlist"))
        sub.addAction(icons.icon("add", theme.TEXT, 16), tr("New playlist..."), lambda: self._new_playlist(tracks))
        pls = self.library.playlists()
        if pls:
            sub.addSeparator()
            for pid, name in pls:
                sub.addAction(name, lambda pid=pid, name=name: self._add_to_playlist(pid, name, tracks))

    def _tile_menu(self, item, pos):
        """Right click on an album or artist tile."""
        menu = QMenu(self)
        menu.addAction(icons.icon("play", theme.TEXT, 16), tr("Play"), lambda: self.player.play_tracks(item.tracks, 0))
        menu.addAction(icons.icon("shuffle", theme.TEXT, 16), tr("Shuffle"), lambda: self._shuffle_list(item.tracks))
        menu.addAction(icons.icon("next", theme.TEXT, 16), tr("Play next"), lambda: self._enqueue(item.tracks, True))
        menu.addAction(icons.icon("queue", theme.TEXT, 16), tr("Add to queue"), lambda: self._enqueue(item.tracks, False))
        self._add_playlist_submenu(menu, item.tracks)
        menu.addSeparator()
        if not hasattr(item, "albums"):           # an album
            self._album_cover_submenu(menu, item)
            menu.addAction(icons.icon("artist", theme.TEXT, 16), tr("Go to artist: {name}", name=item.artist),
                           lambda: self.show_artist_named(item.artist))
        else:
            self._artist_picture_submenu(menu, item)
        menu.exec(pos)

    def _album_menu(self, pos):
        album = self.album_page.album
        if album is None:
            return
        menu = QMenu(self)
        menu.addAction(icons.icon("next", theme.TEXT, 16), tr("Play next"), lambda: self._enqueue(album.tracks, True))
        menu.addAction(icons.icon("queue", theme.TEXT, 16), tr("Add to queue"), lambda: self._enqueue(album.tracks, False))
        self._add_playlist_submenu(menu, album.tracks)
        menu.addSeparator()
        self._album_cover_submenu(menu, album)
        menu.addAction(icons.icon("folder", theme.TEXT, 16), tr("Show in folder"),
                       lambda: self._show_in_folder(album.tracks[0].path))
        menu.exec(pos)

    def _artist_menu(self, pos):
        artist = self.artist_page.artist
        if artist is None:
            return
        menu = QMenu(self)
        menu.addAction(icons.icon("next", theme.TEXT, 16), tr("Play next"), lambda: self._enqueue(artist.tracks, True))
        menu.addAction(icons.icon("queue", theme.TEXT, 16), tr("Add to queue"), lambda: self._enqueue(artist.tracks, False))
        self._add_playlist_submenu(menu, artist.tracks)
        menu.addSeparator()
        self._artist_picture_submenu(menu, artist)
        menu.exec(pos)

    def _album_cover_submenu(self, menu, album):
        current = (self.covers.overrides.get(album.key) or {}).get("source", "auto")
        sub = menu.addMenu(icons.icon("album", theme.TEXT, 16), tr("Album cover"))

        def add(text, source, path=None, icon=None):
            act = sub.addAction(icons.icon(icon, theme.TEXT, 16) if icon else QIcon(), text,
                                lambda: self._set_album_cover(album, source, path))
            act.setCheckable(True)
            act.setChecked(current == source and (path is None or
                                                  (self.covers.overrides.get(album.key) or {}).get("path") == path))

        add(tr("Automatic (Last.fm, else MusicBrainz, else from the songs)"), "auto", icon="sync")
        add(tr("Official cover from Last.fm"), "lastfm", icon="album")
        add(tr("Official cover from MusicBrainz"), "musicbrainz", icon="album")
        add(tr("From the songs (embedded front cover)"), "songs", icon="songs")
        songs = sub.addMenu(tr("From one song..."))
        for t in album.tracks[:40]:
            act = songs.addAction(t.title, lambda t=t: self._set_album_cover(album, "track", t.path))
            act.setCheckable(True)
            act.setChecked(current == "track" and (self.covers.overrides.get(album.key) or {}).get("path") == t.path)
        sub.addSeparator()
        sub.addAction(icons.icon("folder", theme.TEXT, 16), tr("Choose an image on this computer..."),
                      lambda: self._choose_album_image(album))

    def _artist_picture_submenu(self, menu, artist):
        ov = self.covers.artist_overrides.get(artist.key) or {}
        current = ov.get("source", "auto")
        sub = menu.addMenu(icons.icon("artist", theme.TEXT, 16), tr("Artist picture"))
        for text, source, icon in ((tr("Automatic (Last.fm, else Deezer, else from a song)"), "auto", "sync"),
                                   (tr("Photo from Last.fm"), "lastfm", "artist"),
                                   (tr("Photo from Deezer"), "deezer", "artist")):
            act = sub.addAction(icons.icon(icon, theme.TEXT, 16), text,
                                lambda _=False, s=source: self._set_artist_picture(artist, s))
            act.setCheckable(True)
            act.setChecked(current == source)
        songs = sub.addMenu(tr("From one song..."))
        for t in artist.tracks[:40]:
            a = songs.addAction(t.title, lambda t=t: self._set_artist_picture(artist, "track", t.path))
            a.setCheckable(True)
            a.setChecked(current == "track" and ov.get("path") == t.path)
        sub.addSeparator()
        sub.addAction(icons.icon("folder", theme.TEXT, 16), tr("Choose an image on this computer..."),
                      lambda: self._choose_artist_image(artist))

    def _choose_artist_image(self, artist):
        path, _ = QFileDialog.getOpenFileName(self, tr("Choose an artist picture"), self._last_dir(),
                                              f"{tr('Images')} (*.jpg *.jpeg *.png *.webp *.bmp)")
        if not path:
            return
        target = self._store_image(path, "artist_" + artist.key)
        if target:
            self._set_artist_picture(artist, "file", target)

    def _store_image(self, path, key):
        """Copy a chosen picture into the player's data (it stays even if the original moves)."""
        from PySide6.QtGui import QImage
        import hashlib
        img = QImage(path)
        if img.isNull():
            self.toast.show_message(tr("That file is not an image the player can read"), "warning")
            return None
        folder = os.path.join(paths.DATA_DIR, "album_covers")
        os.makedirs(folder, exist_ok=True)
        target = os.path.join(folder, "custom_" + hashlib.sha1(key.encode("utf-8", "surrogatepass")).hexdigest() + ".jpg")
        if max(img.width(), img.height()) > 1600:
            img = img.scaled(1600, 1600, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        if not img.save(target, "JPG", 92):
            self.toast.show_message(tr("Could not save the cover"), "error")
            return None
        return target

    def _set_artist_picture(self, artist, source, path=None):
        overrides = dict(self.settings["artist_pictures"])
        if source == "auto":
            overrides.pop(artist.key, None)
        else:
            overrides[artist.key] = {"source": source, "path": path or ""}
        self.settings.set("artist_pictures", overrides)
        self.covers.artist_overrides = overrides
        self.covers.forget_album("artist:" + artist.key)
        if self.artist_page.artist is not None and self.artist_page.artist.key == artist.key:
            self.artist_page.show_artist(artist)
        self.artists_page.grid.viewport().update()
        self.toast.show_message(tr("Artist picture changed"))

    def _choose_album_image(self, album):
        path, _ = QFileDialog.getOpenFileName(self, tr("Choose an album cover"), os.path.dirname(album.tracks[0].path),
                                              f"{tr('Images')} (*.jpg *.jpeg *.png *.webp *.bmp)")
        if not path:
            return
        from PySide6.QtGui import QImage
        import hashlib
        img = QImage(path)
        if img.isNull():
            self.toast.show_message(tr("That file is not an image the player can read"), "warning")
            return
        # keep a copy, so the cover stays even if the original file moves
        folder = os.path.join(paths.DATA_DIR, "album_covers")
        os.makedirs(folder, exist_ok=True)
        target = os.path.join(folder, "custom_" + hashlib.sha1(album.key.encode("utf-8", "surrogatepass")).hexdigest() + ".jpg")
        if max(img.width(), img.height()) > 1600:
            img = img.scaled(1600, 1600, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        if not img.save(target, "JPG", 92):
            self.toast.show_message(tr("Could not save the cover"), "error")
            return
        self._set_album_cover(album, "file", target)

    def _set_album_cover(self, album, source, path=None):
        overrides = dict(self.settings["album_covers"])
        if source == "auto":
            overrides.pop(album.key, None)
        else:
            overrides[album.key] = {"source": source, "path": path or ""}
        self.settings.set("album_covers", overrides)
        self.covers.overrides = overrides
        self.covers.forget_album(album.key)
        if self.album_page.album is not None and self.album_page.album.key == album.key:
            self.album_page.show_album(album, self.collection())
        for grid in (self.albums_page.grid, self.artist_page.albums_grid, self.album_page.more_grid):
            grid.viewport().update()
        self.toast.show_message(tr("Album cover changed"))

    def _sleep_menu(self):
        menu = QMenu(self)
        mode = self.player.sleep_mode
        off = menu.addAction(tr("Off"), lambda: self._set_sleep(0))
        off.setCheckable(True)
        off.setChecked(mode == "")
        for minutes in (15, 30, 45, 60, 90):
            menu.addAction(tr("{n} minutes", n=minutes), lambda m=minutes: self._set_sleep(m))
        end = menu.addAction(tr("At the end of this song"), lambda: self._set_sleep(-1))
        end.setCheckable(True)
        end.setChecked(mode == "track")
        btn = self.bar.sleep_btn
        menu.exec(btn.mapToGlobal(QPoint(0, -menu.sizeHint().height())))

    def _set_sleep(self, minutes):
        self.player.set_sleep_timer(minutes)
        self.bar.sleep_btn.setChecked(minutes != 0)
        if minutes == 0:
            self.toast.show_message(tr("Sleep timer off"))
        elif minutes == -1:
            self.toast.show_message(tr("Music stops after this song"))
        else:
            self.toast.show_message(tr("Music pauses in {n} minutes", n=minutes))

    def _enqueue(self, tracks, play_next):
        self.player.enqueue(tracks, play_next)
        n = len(tracks)
        what = n_songs(n) if n > 1 else f"“{tracks[0].title}”"
        self.toast.show_message(tr("{what} will play next", what=what) if play_next
                                else tr("Added {what} to the queue", what=what))

    def _set_favorite(self, tracks, value):
        for t in tracks:
            self.library.set_favorite(t, value)
        self._refresh_rows(tracks)
        if self.player.current in tracks:
            self.player.favorite_changed.emit(self.player.current)
        if self._view_key[0] == "favorites":
            self.refresh_view()

    def _tables(self):
        return [self.library_page.table, self.album_page.table, self.artist_page.popular, self.artist_page.all_songs,
                *self.home_page.tables()]

    def _refresh_rows(self, tracks):
        for table in self._tables():
            for t in tracks:
                table.model_.refresh_path(t.path)

    def _on_favorite_changed(self, track):
        self._refresh_rows([track])
        if theme.extra("favorite_toast") and track.favorite:
            self.toast.show_message(tr(theme.extra("favorite_toast")) + " ♥")
        if self._view_key[0] == "favorites":
            self.refresh_view()

    def _on_play_counted(self, track):
        if self._view_key[0] in ("most", "home"):
            self.refresh_view()            # a song may climb in the ranking
        else:
            self._refresh_rows([track])

    def _show_in_folder(self, path):
        try:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        except Exception as exc:
            self.toast.show_message(tr("Cannot open the folder: {error}", error=exc), "error")

    def show_details(self, track):
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("Details") + f" - {track.title}")
        dlg.setMinimumWidth(560)
        form = QFormLayout(dlg)
        form.setContentsMargins(20, 20, 20, 20)
        form.setSpacing(8)

        def row(label, value):
            lab = QLabel(str(value) if value not in (None, "") else "—")
            lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
            lab.setWordWrap(True)
            form.addRow(f"<span style='color:{theme.DIM}'>{tr(label)}</span>", lab)

        row("Title", track.title)
        row("Artist", track.display_artist)
        row("Album", track.album)
        row("Album artist", track.albumartist)
        row("Year", track.year)
        row("Genre", track.genre)
        row("Track / disc", f"{track.track or '-'} / {track.disc or '-'}")
        row("Duration", fmt_time(track.duration))
        row("Format", track.format_label + ("  (Hi-Res)" if track.hires else ""))
        row("Sample rate", f"{track.samplerate / 1000:g} kHz" if track.samplerate else "")
        row("Bit depth", f"{track.bits}-bit" if track.bits else tr("lossy / n.a."))
        row("Channels", track.channels)
        row("Bitrate", f"{track.bitrate // 1000} kbps" if track.bitrate else "")
        row("File size", f"{track.size / 1048576:.1f} MB" if track.size else "")
        row("Plays", track.plays)
        try:
            lyr = meta.find_lyrics(track.path, self.settings["lyrics_order"])
        except Exception:
            lyr = None
        if lyr is None:
            row("Lyrics", tr("none found"))
        else:
            kind = (tr("synced") + (" " + tr("(word timing)") if lyr.has_words else "")) if lyr.synced else tr("plain text")
            row("Lyrics", f"{kind} — {lyr.source}" + (f"\n{lyr.path}" if lyr.path else ""))
        row("File", track.path)
        btn = QPushButton(tr("Close"))
        btn.setToolTip(tr("Close this window"))
        btn.clicked.connect(dlg.accept)
        form.addRow("", btn)
        dlg.exec()

    # ================================================================== playlists
    def _playlist_add_menu(self):
        menu = QMenu(self)
        menu.addAction(icons.icon("add", theme.TEXT, 16), tr("New playlist..."), lambda: self._new_playlist([]))
        menu.addAction(icons.icon("folder", theme.TEXT, 16), tr("Import .m3u playlist..."), self._import_m3u)
        menu.exec(self.add_playlist_btn.mapToGlobal(self.add_playlist_btn.rect().bottomLeft()))

    def _new_playlist(self, tracks):
        name, ok = QInputDialog.getText(self, tr("New playlist"), tr("Playlist name:"), QLineEdit.Normal,
                                        tr("Playlist {n}", n=len(self.library.playlists()) + 1))
        name = (name or "").strip()
        if not ok or not name:
            return None
        pid = self.library.create_playlist(name)
        if tracks:
            self.library.add_to_playlist(pid, [t.path for t in tracks])
        self.reload_playlists()
        self.toast.show_message(tr("Created “{name}”", name=name) +
                                (f" ({n_songs(len(tracks))})" if tracks else ""))
        return pid

    def _add_to_playlist(self, pid, name, tracks):
        self.library.add_to_playlist(pid, [t.path for t in tracks])
        self.toast.show_message(tr("Added {what} to “{name}”", what=n_songs(len(tracks)), name=name))
        if self._view_key == ("playlist", pid):
            self.refresh_view()

    def _remove_from_playlist(self, pid, rows):
        model = self.library_page.table.model_
        positions = {model.list_position(r) for r in rows}
        paths_now = self.library.playlist_paths(pid)
        source = model.source_tracks()
        # map list positions back to playlist entries (missing files were skipped in the view)
        keep_paths = [t.path for i, t in enumerate(source) if i not in positions]
        missing = [p for p in paths_now if p not in {t.path for t in source}]
        self.library.set_playlist_paths(pid, keep_paths + missing)
        self.refresh_view()

    def _move_in_playlist(self, pid, row, delta):
        model = self.library_page.table.model_
        items = [t.path for t in model.source_tracks()]
        i = model.list_position(row)
        j = i + delta
        if not (0 <= i < len(items) and 0 <= j < len(items)):
            return
        items[i], items[j] = items[j], items[i]
        self.library.set_playlist_paths(pid, items)
        self.refresh_view()
        self.library_page.table.selectRow(row + delta)

    def _playlist_menu(self, pos):
        item = self.playlists.itemAt(pos)
        if item is None:
            return
        pid, name = item.data(Qt.UserRole), item.text()
        menu = QMenu(self)
        menu.addAction(icons.icon("play", theme.TEXT, 16), tr("Play"),
                       lambda: self.player.play_tracks(self.library.playlist_tracks(pid), 0))
        menu.addAction(icons.icon("queue", theme.TEXT, 16), tr("Add to queue"),
                       lambda: self._enqueue(self.library.playlist_tracks(pid), False)
                       if self.library.playlist_tracks(pid) else None)
        menu.addSeparator()
        menu.addAction(tr("Rename..."), lambda: self._rename_playlist(pid, name))
        menu.addAction(tr("Export as .m3u8..."), lambda: self._export_playlist(pid, name))
        menu.addSeparator()
        menu.addAction(icons.icon("close", theme.RED_BRIGHT, 16), tr("Delete playlist"), lambda: self._delete_playlist(pid, name))
        menu.exec(self.playlists.mapToGlobal(pos))

    def _rename_playlist(self, pid, name):
        new, ok = QInputDialog.getText(self, tr("Rename playlist"), tr("New name:"), QLineEdit.Normal, name)
        new = (new or "").strip()
        if ok and new:
            self.library.rename_playlist(pid, new)
            self.reload_playlists()
            if self._view_key == ("playlist", pid):
                self.library_page.title.setText(theme.title_text(new))

    def _delete_playlist(self, pid, name):
        if QMessageBox.question(self, tr("Delete playlist"),
                                tr("Delete the playlist “{name}”?", name=name) + "\n" +
                                tr("The songs themselves stay on your disk.")) != QMessageBox.Yes:
            return
        self.library.delete_playlist(pid)
        if self._view_key == ("playlist", pid):
            self._nav_to("home")
        self.reload_playlists()

    def _export_playlist(self, pid, name):
        target, _ = QFileDialog.getSaveFileName(self, tr("Export playlist"),
                                                os.path.join(self._last_dir(), f"{name}.m3u8"), "M3U8 (*.m3u8)")
        if not target:
            return
        try:
            libmod.write_m3u(target, self.library.playlist_tracks(pid))
            self.toast.show_message(tr("Exported “{name}”", name=name))
        except OSError as exc:
            self.toast.show_message(tr("Export failed: {error}", error=exc), "error")

    def _import_m3u(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Import playlist"), self._last_dir(),
                                              f"{tr('Playlists')} (*.m3u *.m3u8)")
        if not path:
            return
        files = libmod.read_m3u(path)
        if not files:
            self.toast.show_message(tr("That playlist has no songs that exist on this computer"), "warning")
            return
        name = os.path.splitext(os.path.basename(path))[0]
        pid = self.library.create_playlist(name)
        self.library.set_playlist_paths(pid, files)
        self.reload_playlists()
        self.toast.show_message(tr("Imported “{name}”", name=name) + f" ({n_songs(len(files))})")

    # ================================================================== library folders / scanning
    def add_music_folder(self):
        folder = QFileDialog.getExistingDirectory(self, tr("Choose your music folder"), paths.default_music_dir())
        if not folder:
            return
        folder = os.path.normpath(folder)
        folders = list(self.settings["library_folders"])
        if folder not in folders:
            folders.append(folder)
            self.settings.set("library_folders", folders)
        self._nav_to("songs")
        self.stack.setCurrentWidget(self.library_page)
        self.rescan()

    def rescan(self):
        folders = self.settings["library_folders"]
        if not folders:
            return
        self.scan_label.setText(tr("Looking for music..."))
        self.scan_label.show()
        b = self.bridge
        self.library.scan(folders,
                          on_progress=lambda done, total, batch: b.scan_progress.emit(done, total),
                          on_done=lambda result: b.scan_done.emit(result))

    def _on_scan_progress(self, done, total):
        if total:
            self.scan_label.setText(tr("Reading tags... {done} / {total}", done=done, total=total))
            if self._view_key[0] in ("songs", "recent") and not self._refresh_timer.isActive():
                self._refresh_timer.start()
        else:
            self.scan_label.setText(tr("Library is up to date"))

    def _on_scan_done(self, result):
        self._collection = None
        if result.get("error"):
            self.scan_label.setText(tr("Scan problem: {error}", error=result["error"]))
            QTimer.singleShot(8000, self.scan_label.hide)
        else:
            added, updated, removed = result.get("added", 0), result.get("updated", 0), result.get("removed", 0)
            parts = []
            if added:
                parts.append(tr("{n} new", n=added))
            if updated:
                parts.append(tr("{n} updated", n=updated))
            if removed:
                parts.append(tr("{n} removed", n=removed))
            self.scan_label.setText(tr("Library") + ": " + (", ".join(parts) if parts else tr("up to date")))
            QTimer.singleShot(4000, self.scan_label.hide)
            if added:
                self.toast.show_message(tr("Added {what} to your library", what=n_songs(added)))
        if self._view_key[0] in ("album", "artist") or self.stack.currentWidget() is self.lyrics_page:
            return          # do not yank the page the user is looking at
        self.refresh_view()
        self._update_welcome()

    def _on_folders_changed(self, folders, removed):
        for folder in removed:
            self.library.remove_folder_tracks(folder, folders)
        self._collection = None
        self.refresh_view()
        if folders:
            self.rescan()
        self._update_welcome()

    # ================================================================== track / lyrics / cover updates
    def _on_track_changed(self, track):
        for table in self._tables():
            table.model_.set_playing(track.path if track else None)
        self.lyrics_page.set_track(track)
        if track is None:
            self.setWindowTitle(APP_NAME)
            self.lyrics_page.view.set_lyrics(None, (theme.say("Nothing playing"), ""))
            self._update_tray_tooltip()
            return
        self.setWindowTitle(f"{track.title} — {track.display_artist}  ·  {APP_NAME}")
        self._update_tray_tooltip()
        self.covers.request_cover(track.path)
        offset = track.lyrics_offset
        self.lyrics_page.set_offset_text(offset)
        for view in self._lyrics_views():
            view.set_offset(offset)
            view.set_lyrics(None, (tr("Loading lyrics..."), ""))
        self.lyrics_page.set_source("")
        self._load_lyrics(track.path)

    def _load_lyrics(self, path):
        """Find lyrics off the UI thread, in the source order chosen in the settings."""
        self._lyrics_path = path
        bridge = self.bridge
        order = list(self.settings["lyrics_order"])

        def job():
            try:
                lyr = meta.find_lyrics(path, order)
            except Exception:
                lyr = None
            bridge.lyrics_ready.emit(path, lyr)

        self._lyrics_pool.submit(job)

    def _on_lyrics_order_changed(self):
        if self.player.current is not None:
            self._load_lyrics(self.player.current.path)

    def _lyrics_views(self):
        views = [self.lyrics_page.view]
        if self._mini is not None:
            views.append(self._mini.lyrics)
        return views

    def _on_lyrics_ready(self, path, lyr):
        if path != self._lyrics_path:
            return
        self._current_lyrics = lyr
        msg = (theme.say("No lyrics for this song"),
               tr("Put a .lrc file with the same name next to the song (or in a 'SYNCED LYRICS' folder), "
                  "or embed lyrics in the file's tags."))
        for view in self._lyrics_views():
            view.set_lyrics(lyr, msg)
        if lyr is None:
            self.lyrics_page.set_source("")
        else:
            kind = ((tr("Synced lyrics") + (" · " + tr("word timing") if lyr.has_words else ""))
                    if lyr.synced else tr("Plain lyrics (not synced)"))
            self.lyrics_page.set_source(f"{kind} · {lyr.source}")

    def _on_cover(self, path, cover, blurred):
        cur = self.player.current
        if cur is None or cur.path != path:
            return
        self.bar.cover.set_image(cover)
        if not self.settings["lyrics_blur_background"]:
            blurred = None
        self.lyrics_page.set_cover(cover, blurred)
        if self._mini is not None:
            self._mini.set_cover(cover, blurred)
        self._current_cover = cover
        self._current_blur = blurred

    def _on_queue_changed(self):
        if self.queue_panel.isVisible():
            self.queue_panel.refresh(self.player)

    def _on_state_changed(self, state):
        for table in self._tables():
            table.viewport().update()
        if self._tray is not None:
            self._tray_play.setText(tr("Pause") if state == audio.STATE_PLAYING else tr("Play"))

    def _lyrics_position(self):
        return self.player.position()

    # ================================================================== lyrics view controls
    def toggle_lyrics(self):
        if self.stack.currentWidget() is self.lyrics_page:
            self.leave_lyrics()
        else:
            self.show_lyrics()

    def show_lyrics(self):
        if self.stack.currentWidget() is not self.lyrics_page:
            self._before_lyrics = self.stack.currentWidget()
        self.stack.setCurrentWidget(self.lyrics_page)
        self.sidebar.hide()
        self.bar.lyrics_btn.setChecked(True)

    def leave_lyrics(self):
        if self.isFullScreen():
            self.toggle_fullscreen()
        self.sidebar.show()
        self.bar.lyrics_btn.setChecked(False)
        if self.stack.currentWidget() is self.lyrics_page:
            back = getattr(self, "_before_lyrics", None) or self.library_page
            self.stack.setCurrentWidget(back)
        self._update_welcome()

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showMaximized() if self._was_maximized else self.showNormal()
            self.bar.show()
            self.lyrics_page.toolbar.show()
            self.unsetCursor()
            QApplication.instance().removeEventFilter(self)
            self._idle_timer.stop()
        else:
            self._was_maximized = self.isMaximized()
            if self.stack.currentWidget() is not self.lyrics_page:
                self.show_lyrics()
            self.showFullScreen()
            QApplication.instance().installEventFilter(self)
            self._idle_timer.start()
        self.lyrics_page.set_fullscreen_icon(self.isFullScreen())

    def _hide_bar_idle(self):
        if self.isFullScreen() and self.stack.currentWidget() is self.lyrics_page:
            self.bar.hide()
            self.lyrics_page.toolbar.hide()
            self.setCursor(Qt.BlankCursor)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseMove and self.isFullScreen():
            if not self.bar.isVisible():
                self.bar.show()
                self.lyrics_page.toolbar.show()
                self.unsetCursor()
            self._idle_timer.start()
        return False

    def change_lyrics_size(self, step):
        size = max(14, min(96, self.settings["lyrics_font_size"] + step))
        self.settings.set("lyrics_font_size", size)
        self._apply_lyrics_style()
        self.toast.show_message(tr("Lyrics text size: {size} px", size=size), ms=1200)
        if self._settings_dialog is not None:
            self._settings_dialog.sync_lyrics_controls()

    def change_lyrics_offset(self, delta):
        track = self.player.current
        if track is None:
            return
        offset = round(track.lyrics_offset + delta, 2)
        self.library.set_lyrics_offset(track, offset)
        for view in self._lyrics_views():
            view.set_offset(offset)
        self.lyrics_page.set_offset_text(offset)
        if abs(offset) < 0.05:
            text = tr("Lyrics timing: original")
        elif offset > 0:
            text = tr("Lyrics {s} s earlier for this song", s=f"{abs(offset):.1f}")
        else:
            text = tr("Lyrics {s} s later for this song", s=f"{abs(offset):.1f}")
        self.toast.show_message(text, ms=1400)

    def _swap_cover_side(self):
        side = "right" if self.settings["lyrics_cover_side"] == "left" else "left"
        self.settings.set("lyrics_cover_side", side)
        self._apply_lyrics_style()

    def _apply_lyrics_style(self):
        s = self.settings
        style = dict(family=s["lyrics_font_family"], size=s["lyrics_font_size"], bold=s["lyrics_bold"],
                     align=s["lyrics_align"], active=s["lyrics_active_color"],
                     upcoming=s["lyrics_upcoming_color"], past=s["lyrics_past_color"],
                     karaoke=s["lyrics_karaoke"])
        for view in self._lyrics_views():
            view.set_style(**style)
        self.lyrics_page.set_cover_side(s["lyrics_cover_side"])

    # ================================================================== queue / mini / settings
    def toggle_queue(self):
        show = not self.queue_panel.isVisible()
        self.queue_panel.setVisible(show)
        self.bar.queue_btn.setChecked(show)
        if show:
            self.queue_panel.refresh(self.player)

    def show_mini(self):
        if self._mini is None:
            self._mini = MiniPlayer(self.player, self.settings)
            self._mini.setWindowIcon(self.windowIcon())
            self._mini.expand_requested.connect(self.show_full)
            self._mini.closed.connect(self._on_mini_closed)
            self._apply_lyrics_style()
            if self._current_lyrics is not None or self._lyrics_path:
                self._mini.lyrics.set_offset(self.player.current.lyrics_offset if self.player.current else 0.0)
                self._mini.lyrics.set_lyrics(self._current_lyrics, (theme.say("No lyrics for this song"), ""))
            self._mini.lyrics.set_sources(self._lyrics_position, lambda: self.player.state == audio.STATE_PLAYING)
            self._mini.set_cover(self._current_cover, self._current_blur)
        if self.isFullScreen():
            self.toggle_fullscreen()
        self._mini.show()
        winutil.dark_title_bar(self._mini)
        self._mini.raise_()
        self._mini.activateWindow()
        self.hide()

    def show_full(self):
        if self._mini is not None and self._mini.isVisible():
            self._mini.save_geometry()
            self._mini.hide()
        self.show()
        self.raise_()
        self.activateWindow()

    def _on_mini_closed(self):
        if not self._quitting and not self.isVisible():
            self.show_full()

    def open_settings(self):
        if self._settings_dialog is None:
            dlg = SettingsDialog(self.settings, self)
            dlg.lyrics_style_changed.connect(self._apply_lyrics_style)
            dlg.lyrics_order_changed.connect(self._on_lyrics_order_changed)
            dlg.lyrics_style_changed.connect(lambda: self._on_cover_refresh())
            dlg.audio_changed.connect(self.player.apply_output_settings)
            dlg.folders_changed.connect(self._on_folders_changed)
            dlg.rescan_requested.connect(self.rescan)
            dlg.update_check_requested.connect(lambda: self.check_for_update(manual=True))
            dlg.restart_requested.connect(self.restart)
            dlg.online_covers_changed.connect(self._on_online_covers_changed)
            dlg.rain_changed.connect(self._set_rain)
            self._settings_dialog = dlg
        self._settings_dialog.show()
        self._settings_dialog.raise_()
        self._settings_dialog.activateWindow()

    def _set_rain(self, on):
        if self._welcome_rain is not None:
            self._welcome_rain.setVisible(on)
        self.lyrics_page.set_rain(on)

    def _on_online_covers_changed(self, enabled):
        self.covers.online.enabled = enabled
        self.albums_page.grid.viewport().update()

    def _on_cover_refresh(self):
        if self.player.current is not None:
            self.covers.request_cover(self.player.current.path)

    def restart(self):
        """Theme and language need a fresh start; the music continues where it was."""
        playing = self.player.state == audio.STATE_PLAYING
        env = dict(os.environ, T9_WAIT_PID=str(os.getpid()))
        if playing:
            env["T9_RESUME_PLAYING"] = "1"
        else:
            env.pop("T9_RESUME_PLAYING", None)
        if getattr(sys, "frozen", False):
            cmd = [sys.executable]
        else:
            cmd = [sys.executable, os.path.abspath(sys.argv[0])]
        try:
            subprocess.Popen(cmd, env=env, close_fds=True)
        except Exception as exc:
            QMessageBox.warning(self, tr("Restart"), tr("Please start the player again yourself.") + f"\n{exc}")
        self.quit()

    # ================================================================== updates
    def check_for_update(self, manual=False):
        folder = self.settings["update_folder"]
        online = self.settings["online_updates"] or manual
        bridge = self.bridge

        def job():
            found = []
            if folder:
                try:
                    hit = updater.find_update(folder)
                    if hit:
                        found.append((hit[0], hit[1], 0, ""))
                except Exception:
                    pass
            if online:
                try:
                    hit = updater.check_github()
                    if hit:
                        found.append(hit)
                except Exception:
                    if manual and not found:
                        bridge.update_checked.emit("offline", True)
                        return
            found.sort(key=lambda f: updater.parse_version(f[0]))
            bridge.update_checked.emit(found[-1] if found else None, manual)

        self._files_pool.submit(job)

    def _on_update_checked(self, found, manual):
        parent = self._settings_dialog if (self._settings_dialog and self._settings_dialog.isVisible()) else self
        if found == "offline":
            QMessageBox.warning(parent, tr("Updates"), tr("Could not reach GitHub - check the internet connection"))
            return
        if found is None:
            if manual:
                QMessageBox.information(parent, tr("Updates"),
                                        tr("Your version is up to date.") + "\n\n" +
                                        tr("You have {app} {version} - the newest version available.",
                                           app=APP_NAME, version=APP_VERSION))
            return
        version, source, size, notes = found
        self.toast.show_message(tr("New version {version} is available", version=version) + " ✨")
        if self._tray is not None:
            self._tray.showMessage(APP_NAME, tr("New version {version} is available", version=version),
                                   self.windowIcon(), 6000)
        parent = self._settings_dialog if (self._settings_dialog and self._settings_dialog.isVisible()) else self
        answer = QMessageBox.question(
            parent, tr("Update available"),
            tr("{app} {version} is ready to install (you have {current}).", app=APP_NAME, version=version,
               current=APP_VERSION) + "\n\n" +
            (tr("What's new:") + "\n" + (notes[:700] + ("..." if len(notes) > 700 else "")) + "\n\n" if notes else "") +
            tr("Install it now? The player closes for a moment and starts again.") + "\n" +
            tr("Your library, playlists and settings stay as they are."))
        if answer != QMessageBox.Yes:
            return
        if source.startswith("https://"):
            self._download_update(source, size, parent, version)
        else:
            self._install_update(source, parent)

    def _download_update(self, url, size, parent, version=""):
        from PySide6.QtWidgets import QProgressDialog
        dlg = QProgressDialog(tr("Downloading the update..."), tr("Cancel"), 0, 100, parent)
        dlg.setWindowTitle(tr("Update"))
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.setValue(0)
        self._update_dialog = dlg
        self._update_cancelled = False
        dlg.canceled.connect(lambda: setattr(self, "_update_cancelled", True))
        bridge = self.bridge

        def progress(done, total):
            if self._update_cancelled:
                raise RuntimeError("cancelled")
            bridge.update_progress.emit(done, total)

        def job():
            try:
                bridge.update_downloaded.emit(updater.download(url, size, progress, version=version))
            except Exception as exc:
                bridge.update_downloaded.emit(exc)

        self._files_pool.submit(job)

    def _on_update_progress(self, done, total):
        dlg = getattr(self, "_update_dialog", None)
        if dlg is not None and total > 0:
            dlg.setValue(int(done * 100 / total))
            dlg.setLabelText(tr("Downloading the update...") + f"  {done / 1048576:.0f} / {total / 1048576:.0f} MB")

    def _on_update_downloaded(self, result):
        dlg, self._update_dialog = getattr(self, "_update_dialog", None), None
        if dlg is not None:
            dlg.close()
        if isinstance(result, Exception):
            if not self._update_cancelled:
                self.toast.show_message(tr("The update could not be downloaded: {error}", error=result), "error")
            return
        self._install_update(result, self)

    def _install_update(self, path, parent):
        try:
            self.save_session()
            updater.launch_installer(path)
        except Exception as exc:
            QMessageBox.warning(parent, tr("Update"), tr("Could not start the installer:") + f"\n{exc}")
            return
        self.quit()

    # ================================================================== tray
    def _setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        tray = QSystemTrayIcon(self.windowIcon() if not self.windowIcon().isNull() else QIcon(paths.ICON_FILE), self)
        menu = QMenu()
        self._tray_play = menu.addAction(tr("Play"), self.player.play_pause)
        menu.addAction(tr("Next"), self.player.next)
        menu.addAction(tr("Previous"), self.player.previous)
        menu.addSeparator()
        menu.addAction(tr("Show player"), self.show_full)
        menu.addAction(tr("Compact player"), self.show_mini)
        menu.addSeparator()
        menu.addAction(tr("Quit"), self.quit)
        tray.setContextMenu(menu)
        tray.activated.connect(self._on_tray)
        tray.setToolTip(APP_NAME)
        tray.show()
        self._tray = tray
        self._tray_menu = menu

    def _on_tray(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            if self.isVisible() and not self.isMinimized():
                self.hide() if self.settings["minimize_to_tray"] else self.activateWindow()
            else:
                self.show_full()
                if self.isMinimized():
                    self.showNormal()

    def _update_tray_tooltip(self):
        if self._tray is None:
            return
        t = self.player.current
        self._tray.setToolTip(f"{t.title} — {t.display_artist}"[:120] if t else APP_NAME)

    # ================================================================== session
    def save_session(self):
        p = self.player
        queue = [t.path for t in p.queue[:3000]]
        data = {
            "queue": queue,
            "index": p.index if 0 <= p.index < len(queue) else 0,
            "position": round(p.position(), 2) if p.current else 0.0,
            "view": list(self._view_key),
            "queue_open": self.queue_panel.isVisible(),
        }
        write_json_atomic(paths.SESSION_FILE, data)

    def restore_session(self):
        data = read_json(paths.SESSION_FILE, {})
        queue = [q for q in data.get("queue", []) if isinstance(q, str)]
        if not queue:
            return
        tracks = []
        index = int(data.get("index", 0) or 0)
        new_index = 0
        for i, path in enumerate(queue):
            if not os.path.isfile(path):
                continue
            t = self.library.get(path)
            if t is None:
                try:
                    t = self.library.track_for_path(path)
                except Exception:
                    continue
            if i == index:
                new_index = len(tracks)
            tracks.append(t)
        if not tracks:
            return
        pos = float(data.get("position", 0.0) or 0.0)
        resume = bool(os.environ.pop("T9_RESUME_PLAYING", ""))
        self.player.play_tracks(tracks, new_index, position=pos, paused=not resume)
        if data.get("queue_open"):
            self.toggle_queue()

    def _restore_geometry(self):
        geo = self.settings["window_geometry"]
        if geo:
            try:
                self.restoreGeometry(QByteArray.fromBase64(geo.encode("ascii")))
                return
            except Exception:
                pass
        self.resize(1360, 820)

    # ================================================================== keyboard / drops / close
    def handle_key(self, event):
        """Global shortcuts (installed via KeyFilter). Returns True when handled."""
        key = event.key()
        mods = event.modifiers()
        ctrl = bool(mods & Qt.ControlModifier)
        focus = QApplication.focusWidget()
        typing = isinstance(focus, (QLineEdit, QAbstractSpinBox)) or (
            isinstance(focus, QComboBox) and focus.isEditable())
        in_table = isinstance(focus, QTableView)
        p = self.player
        if event.isAutoRepeat() and key not in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            # holding a key must not toggle play/pause, shuffle ... over and over
            return not typing and key in (Qt.Key_Space, Qt.Key_M, Qt.Key_S, Qt.Key_R, Qt.Key_F, Qt.Key_L, Qt.Key_Q)
        if key in (Qt.Key_MediaPlay, Qt.Key_MediaTogglePlayPause, Qt.Key_MediaPause):
            p.play_pause()
            return True
        if key == Qt.Key_MediaNext:
            p.next()
            return True
        if key == Qt.Key_MediaPrevious:
            p.previous()
            return True
        if ctrl and key == Qt.Key_F:
            self.show_full()
            if self.stack.currentWidget() not in (self.library_page,):
                self._nav_to("songs")
            self.library_page.search.setFocus()
            self.library_page.search.selectAll()
            return True
        if ctrl and key == Qt.Key_O:
            self.open_files()
            return True
        if ctrl and key == Qt.Key_M:
            if self._mini is not None and self._mini.isVisible():
                self.show_full()
            else:
                self.show_mini()
            return True
        if ctrl and key == Qt.Key_Comma:
            self.open_settings()
            return True
        if ctrl and key == Qt.Key_Right:
            p.next()
            return True
        if ctrl and key == Qt.Key_Left:
            p.previous()
            return True
        if ctrl and key in (Qt.Key_Equal, Qt.Key_Plus):
            self.change_lyrics_size(2)
            return True
        if ctrl and key == Qt.Key_Minus:
            self.change_lyrics_size(-2)
            return True
        if key == Qt.Key_F11:
            if self._mini is not None and self._mini.isVisible():
                self.show_full()
            self.toggle_fullscreen()
            return True
        if typing:
            if key == Qt.Key_Escape and isinstance(focus, QLineEdit):
                focus.clear() if focus.text() else self.library_page.table.setFocus()
                return True
            return False
        if mods & (Qt.ControlModifier | Qt.AltModifier):
            if key == Qt.Key_Left and mods & Qt.AltModifier:
                self.go_back()
                return True
            return False
        if key == Qt.Key_Space:
            p.play_pause()
            return True
        if key == Qt.Key_Right:
            p.seek_relative(5)
            return True
        if key == Qt.Key_Left:
            p.seek_relative(-5)
            return True
        if key in (Qt.Key_Up, Qt.Key_Down) and not in_table:
            p.set_volume(p.volume + (0.05 if key == Qt.Key_Up else -0.05))
            return True
        if key in (Qt.Key_Escape, Qt.Key_Backspace):
            if self.isFullScreen():
                self.toggle_fullscreen()
            elif self.stack.currentWidget() is self.lyrics_page:
                self.leave_lyrics()
            elif self._view_key[0] in ("album", "artist"):
                self.go_back()
            elif self.queue_panel.isVisible():
                self.toggle_queue()
            return True
        if in_table and Qt.Key_A <= key <= Qt.Key_Z and key not in (Qt.Key_L, Qt.Key_M, Qt.Key_S, Qt.Key_R, Qt.Key_F, Qt.Key_Q):
            return False
        if key == Qt.Key_L:
            if self._mini is not None and self._mini.isVisible():
                self._mini.btn_lyrics.toggle()
            else:
                self.toggle_lyrics()
            return True
        if key == Qt.Key_M:
            p.toggle_mute()
            return True
        if key == Qt.Key_S:
            p.set_shuffle(not p.shuffle)
            return True
        if key == Qt.Key_R:
            p.cycle_repeat()
            return True
        if key == Qt.Key_F:
            p.toggle_favorite()
            return True
        if key == Qt.Key_Q:
            self.toggle_queue()
            return True
        if key == Qt.Key_BracketLeft:
            self.change_lyrics_offset(0.1)
            return True
        if key == Qt.Key_BracketRight:
            self.change_lyrics_offset(-0.1)
            return True
        return False

    def on_media_key(self, action):
        p = self.player
        {"play_pause": p.play_pause, "next": p.next, "previous": p.previous, "stop": p.pause}.get(action, lambda: None)()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        files = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if files:
            replace = not (event.modifiers() & Qt.ShiftModifier)
            self.play_files(files, replace=replace)
            event.acceptProposedAction()

    def _tick(self):
        if self.isVisible():
            self.bar.tick()
        if self._mini is not None:
            self._mini.tick()

    def closeEvent(self, event):
        if not self._quitting and self.settings["minimize_to_tray"] and self._tray is not None:
            event.ignore()
            self.hide()
            self.toast.show_message(tr("Still playing in the tray"))
            return
        self.quit()
        event.accept()

    def quit(self):
        if self._quitting:
            return
        self._quitting = True
        try:
            if not self.isFullScreen():
                self.settings.set("window_geometry", bytes(self.saveGeometry().toBase64()).decode("ascii"), save=False)
            if self._mini is not None:
                self._mini.save_geometry()
            self.save_session()
            self.player.save_volume()
            self.settings.save()
        except Exception:
            pass
        if self._tray is not None:
            self._tray.hide()
        if self._mini is not None:
            self._mini.close()
        QApplication.instance().quit()

    def shutdown(self):
        self._tick_timer.stop()
        self._lyrics_pool.shutdown(wait=False, cancel_futures=True)
        self._files_pool.shutdown(wait=False, cancel_futures=True)
