"""Albums / Artists grids and the album / artist pages (Spotify-like)."""

from PySide6.QtCore import QAbstractListModel, QModelIndex, QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QListView, QScrollArea, QSizePolicy, QStyle, QStyledItemDelegate,
                               QVBoxLayout, QWidget)

from .. import icons, theme
from ..covers import dominant_color
from ..i18n import albums as n_albums, duration_long, songs as n_songs, times as n_times, tr
from .library_view import COL_ALBUM, COL_FORMAT, COL_NUM, COL_PLAYS, COL_TIME, COL_TITLE, TrackTable
from .widgets import CoverWidget, IconButton, paint_placeholder

TILE_MIN = 180


# ============================================================================ tiles

class TileModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = []

    def set_items(self, items):
        self.beginResetModel()
        self.items = list(items)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        item = self.items[index.row()]
        if role == Qt.DisplayRole:
            return getattr(item, "title", None) or getattr(item, "name", "")
        if role == Qt.ToolTipRole:
            return getattr(item, "title", None) or getattr(item, "name", "")
        if role == Qt.UserRole:
            return item
        return None


class TileDelegate(QStyledItemDelegate):
    def __init__(self, view, covers, round_art):
        super().__init__(view)
        self.view = view
        self.covers = covers
        self.round_art = round_art
        self._f1 = QFont(theme.FONT)
        self._f1.setPixelSize(14)
        self._f1.setWeight(QFont.DemiBold)
        self._f2 = QFont(theme.FONT)
        self._f2.setPixelSize(12)

    def sizeHint(self, option, index):
        return self.view.gridSize() - QSize(4, 4)

    def art_rect(self, rect):
        side = rect.width() - 20
        return QRectF(rect.left() + 10, rect.top() + 10, side, side)

    def play_rect(self, rect):
        art = self.art_rect(rect)
        return QRectF(art.right() - 52, art.bottom() - 52, 44, 44)

    def paint(self, p, option, index):
        item = index.data(Qt.UserRole)
        if item is None:
            return
        r = option.rect
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        hovered = bool(option.state & QStyle.State_MouseOver)
        if hovered:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.HOVER))
            p.drawRoundedRect(QRectF(r).adjusted(2, 2, -2, -2), 8, 8)
        art = self.art_rect(r)
        path = QPainterPath()
        if self.round_art:
            path.addEllipse(art)
        else:
            path.addRoundedRect(art, 6, 6)
        if hasattr(item, "albums"):           # artist
            pm = self.covers.artist_art(item, 300)
        else:
            pm = self.covers.album_art(item, 300)
        if pm:
            p.save()
            p.setClipPath(path)
            p.drawPixmap(art, pm, QRectF(pm.rect()))
            p.restore()
        elif pm is False:
            p.save()
            p.setClipPath(path)
            paint_placeholder(p, art, 0 if not self.round_art else art.width() / 2)
            p.restore()
        else:
            p.fillPath(path, QColor(theme.PANEL))
        if hovered:
            btn = self.play_rect(r)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 90))
            p.drawEllipse(btn.adjusted(-1, 1, 1, 3))
            p.setBrush(QColor(theme.RED_BRIGHT if self.view.hover_play else theme.RED))
            p.drawEllipse(btn)
            ic = icons.pixmap("play", theme.ON_ACCENT, 22)
            p.drawPixmap(btn.adjusted(11, 11, -11, -11), ic, QRectF(ic.rect()))
        text_w = int(r.width() - 20)
        y = art.bottom() + 8
        p.setFont(self._f1)
        p.setPen(QColor(theme.TEXT))
        title = getattr(item, "title", None) or item.name
        p.drawText(QRectF(r.left() + 10, y, text_w, 20), Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetrics(self._f1).elidedText(title, Qt.ElideRight, text_w))
        p.setFont(self._f2)
        p.setPen(QColor(theme.DIM))
        if hasattr(item, "albums"):
            sub = tr("Artist") + " · " + n_songs(len(item.tracks))
        else:
            sub = " · ".join(x for x in (item.year, item.artist) if x)
        p.drawText(QRectF(r.left() + 10, y + 20, text_w, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetrics(self._f2).elidedText(sub, Qt.ElideRight, text_w))
        p.restore()


class TileGrid(QListView):
    open_item = Signal(object)
    play_item = Signal(object)
    item_menu = Signal(object, QPoint)       # item, global position (right click)

    def __init__(self, covers, round_art=False, parent=None, one_row=False):
        super().__init__(parent)
        self.hover_play = False
        self.one_row = one_row
        self.model_ = TileModel(self)
        self.setModel(self.model_)
        self.delegate = TileDelegate(self, covers, round_art)
        self.setItemDelegate(self.delegate)
        self.setViewMode(QListView.IconMode)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setMouseTracking(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(30)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("QListView { background: transparent; border: none; }")
        self.setGridSize(QSize(TILE_MIN, TILE_MIN + 60))
        self._all = []
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self.viewport().update)
        covers.thumb_ready.connect(lambda *_: self._timer.start())
        covers.album_art_ready.connect(lambda *_: self._timer.start())
        # a scrollbar that comes and goes changes the width, which changes the number of
        # columns, which changes whether the scrollbar is needed ... -> flicker. Keep it fixed.
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff if one_row else Qt.ScrollBarAlwaysOn)
        self._grid_key = None
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_menu)

    def _on_menu(self, pos):
        idx = self.indexAt(pos)
        if idx.isValid():
            self.item_menu.emit(idx.data(Qt.UserRole), self.viewport().mapToGlobal(pos))

    def set_items(self, items):
        self._all = list(items)
        self._apply()

    def _usable_width(self):
        bar = 0 if self.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff else self.verticalScrollBar().sizeHint().width()
        return max(200, self.width() - 2 * self.frameWidth() - bar - 4)

    def _columns(self):
        return max(2, self._usable_width() // TILE_MIN)

    def _apply(self):
        items = self._all[: self._columns()] if self.one_row else self._all
        self.model_.set_items(items)
        self._fit()

    def _fit(self):
        cols = self._columns()
        tile = int(self._usable_width() / cols)
        if self._grid_key != tile:
            self._grid_key = tile
            self.setGridSize(QSize(tile, tile + 46))
        if self.one_row:
            self.setFixedHeight(tile + 54 if self.model_.rowCount() else 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        before = self.model_.rowCount()
        if self.one_row and before != min(len(self._all), self._columns()):
            self._apply()
        else:
            self._fit()

    def wheelEvent(self, event):
        if self.one_row:
            event.ignore()
            return
        super().wheelEvent(event)

    def _hit_play(self, pos):
        idx = self.indexAt(pos)
        if not idx.isValid():
            return None, False
        return idx, self.delegate.play_rect(self.visualRect(idx)).contains(pos)

    def mouseMoveEvent(self, event):
        idx, on_play = self._hit_play(event.position().toPoint())
        if on_play != self.hover_play:
            self.hover_play = on_play
            self.viewport().update()
        self.setCursor(Qt.PointingHandCursor if idx is not None else Qt.ArrowCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            idx, on_play = self._hit_play(event.position().toPoint())
            if idx is not None:
                item = idx.data(Qt.UserRole)
                (self.play_item if on_play else self.open_item).emit(item)
                return
        super().mouseReleaseEvent(event)


class CollectionPage(QWidget):
    """'Albums' or 'Artists': heading, search, sort, grid of tiles."""

    def __init__(self, covers, kind, parent=None):
        super().__init__(parent)
        self.kind = kind
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 22, 20, 0)
        lay.setSpacing(10)
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.title = QLabel(theme.title_text(tr("Albums") if kind == "albums" else tr("Artists")))
        self.title.setObjectName("H1")
        self.stats = QLabel("")
        self.stats.setObjectName("Dim")
        titles.addWidget(self.title)
        titles.addWidget(self.stats)
        head.addLayout(titles, 1)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Search albums...") if kind == "albums" else tr("Search artists..."))
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(260)
        self.search.addAction(icons.icon("search", theme.DIM, 16), QLineEdit.LeadingPosition)
        self.search.setToolTip(tr("Type to filter the list instantly"))
        self.sort = QComboBox()
        self.sort.setToolTip(tr("How the tiles are ordered"))
        if kind == "albums":
            for label, key in ((tr("Title A-Z"), "title"), (tr("Newest first"), "year"),
                               (tr("Artist"), "artist"), (tr("Most played"), "plays")):
                self.sort.addItem(label, key)
        else:
            for label, key in ((tr("Name A-Z"), "name"), (tr("Most songs"), "songs"), (tr("Most played"), "plays")):
                self.sort.addItem(label, key)
        head.addWidget(self.search, 0, Qt.AlignVCenter)
        head.addWidget(self.sort, 0, Qt.AlignVCenter)
        lay.addLayout(head)
        self.grid = TileGrid(covers, round_art=kind == "artists")
        lay.addWidget(self.grid, 1)
        self._collection = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self.refresh)
        self.search.textChanged.connect(lambda _: self._timer.start())
        self.sort.currentIndexChanged.connect(lambda _: self.refresh())

    def set_collection(self, collection):
        self._collection = collection
        self.refresh()

    def refresh(self):
        c = self._collection
        if c is None:
            return
        key = self.sort.currentData()
        items = c.albums_sorted(key) if self.kind == "albums" else c.artists_sorted(key)
        text = self.search.text().strip().casefold()
        if text:
            if self.kind == "albums":
                items = [a for a in items if text in a.title.casefold() or text in a.artist.casefold()]
            else:
                items = [a for a in items if text in a.name.casefold()]
        self.grid.set_items(items)
        n = len(items)
        self.stats.setText(n_albums(n) if self.kind == "albums" else
                           f"{n} " + (tr("artist") if n == 1 else tr("artists")))


# ============================================================================ album / artist pages

class HeroHeader(QWidget):
    """Gradient from the cover's colour down to the page background (like Spotify)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.color = QColor(theme.RED_DARK)

    def paintEvent(self, event):
        p = QPainter(self)
        grad = QLinearGradient(0, 0, 0, self.height())
        top = QColor(self.color)
        mid = QColor(self.color)
        mid.setAlpha(110)
        grad.setColorAt(0, top)
        grad.setColorAt(0.55, mid)
        grad.setColorAt(1, QColor(theme.BG))
        p.fillRect(self.rect(), grad)


class _Link(QLabel):
    clicked = Signal()

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()

    def enterEvent(self, event):
        f = self.font()
        f.setUnderline(True)
        self.setFont(f)

    def leaveEvent(self, event):
        f = self.font()
        f.setUnderline(False)
        self.setFont(f)


class DetailPage(QScrollArea):
    """Common layout of the album and artist pages."""
    back_requested = Signal()
    play_tracks = Signal(list, int)
    play_toggle = Signal(list, int)
    shuffle_tracks = Signal(list)
    open_album = Signal(object)
    open_artist = Signal(str)
    track_menu = Signal(object, QPoint)
    more_menu = Signal(QPoint)
    item_menu = Signal(object, QPoint)

    def __init__(self, covers, is_playing_fn, kind, parent=None):
        super().__init__(parent)
        self.covers = covers
        self.kind = kind
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.verticalScrollBar().setSingleStep(40)
        body = QWidget()
        body.setObjectName("PageBody")
        body.setAutoFillBackground(False)
        body.setStyleSheet("#PageBody { background: transparent; }")
        self.viewport().setAutoFillBackground(False)
        self.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.setWidget(body)
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(0, 0, 0, 30)
        self.body.setSpacing(0)

        self.hero = HeroHeader()
        self.hero.setFixedHeight(300)
        hl = QHBoxLayout(self.hero)
        hl.setContentsMargins(32, 52, 32, 24)
        hl.setSpacing(26)
        self.cover = CoverWidget(radius=110 if kind == "artist" else 6, shadow=True)
        self.cover.setFixedSize(228, 228)
        hl.addWidget(self.cover, 0, Qt.AlignBottom)
        texts = QVBoxLayout()
        texts.setSpacing(4)
        texts.addStretch(1)
        self.kind_label = QLabel(theme.title_text(tr("Album") if kind == "album" else tr("Artist")))
        self.kind_label.setStyleSheet(f"color: {theme.TEXT}; font-size: 13px; font-weight: 600;")
        self.title = QLabel("")
        self.title.setWordWrap(False)
        self.title.setStyleSheet(f"color: #ffffff; {theme.title_css(64)}")
        self.title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        meta = QHBoxLayout()
        meta.setSpacing(0)
        self.meta_link = _Link("")
        self.meta_link.setStyleSheet(f"color: {theme.TEXT}; font-size: 13px; font-weight: 700;")
        self.meta_link.clicked.connect(self._on_meta_link)
        self.meta = QLabel("")
        self.meta.setStyleSheet(f"color: {theme.TEXT}; font-size: 13px;")
        meta.addWidget(self.meta_link)
        meta.addWidget(self.meta)
        meta.addStretch(1)
        texts.addWidget(self.kind_label)
        texts.addWidget(self.title)
        texts.addLayout(meta)
        hl.addLayout(texts, 1)
        self.body.addWidget(self.hero)

        self.back = IconButton("back", tr("Back"), 36, 20, parent=self.hero)
        self.back.move(16, 12)
        self.back.clicked.connect(self.back_requested)

        actions = QHBoxLayout()
        actions.setContentsMargins(32, 16, 32, 12)
        actions.setSpacing(14)
        self.play_btn = IconButton("play", tr("Play"), 56, 26, filled=True)
        self.shuffle_btn = IconButton("shuffle", tr("Play in random order"), 42, 26)
        self.more_btn = IconButton("more", tr("More options"), 42, 24)
        actions.addWidget(self.play_btn)
        actions.addWidget(self.shuffle_btn)
        actions.addWidget(self.more_btn)
        actions.addStretch(1)
        self.body.addLayout(actions)
        self.play_btn.clicked.connect(lambda: self.play_tracks.emit(self.tracks, 0))
        self.shuffle_btn.clicked.connect(lambda: self.shuffle_tracks.emit(self.tracks))
        self.more_btn.clicked.connect(lambda: self.more_menu.emit(self.more_btn.mapToGlobal(QPoint(0, self.more_btn.height()))))
        self.tracks = []
        self._is_playing = is_playing_fn

    def _section(self, text):
        lab = QLabel(theme.title_text(text))
        lab.setStyleSheet(f"color: {theme.TEXT}; {theme.title_css(22)} padding: 18px 32px 6px 32px;")
        self.body.addWidget(lab)
        return lab

    def _table(self, columns):
        table = TrackTable(self.covers, self._is_playing, embedded=True)
        table.set_visible_columns(columns)
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(24, 0, 24, 0)
        wl.addWidget(table)
        self.body.addWidget(wrap)
        table.activated_row.connect(lambda row, t=table: self.play_tracks.emit(t.model_.tracks(), row))
        table.play_clicked.connect(lambda row, t=table: self.play_toggle.emit(t.model_.tracks(), row))
        table.context_requested.connect(lambda pos, t=table: self.track_menu.emit(t, pos))
        return table

    def _grid(self, round_art, one_row):
        grid = TileGrid(self.covers, round_art=round_art, one_row=one_row)
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(22, 0, 22, 0)
        wl.addWidget(grid)
        self.body.addWidget(wrap)
        grid.open_item.connect(self.open_album)
        grid.play_item.connect(lambda album: self.play_tracks.emit(album.tracks, 0))
        grid.item_menu.connect(self.item_menu)
        return grid

    def _fit_title(self, text):
        """Biggest heading size (max 72 px) that fits the available width."""
        avail = max(200, self.viewport().width() - 228 - 32 * 2 - 26 - 10)
        size = 72
        while size > 26:
            f = QFont(theme.TITLE_FONT)
            f.setPixelSize(int(size * theme.TITLE_SCALE))
            f.setWeight(QFont.Weight(theme.TITLE_WEIGHT))
            if QFontMetrics(f).horizontalAdvance(text) <= avail:
                break
            size -= 6
        self.title.setStyleSheet(f"color: #ffffff; {theme.title_css(size)}")
        self.title.setText(text)

    def _load_cover(self, image_fn):
        """Load the big cover off the UI thread, then colour the header with it."""
        token = object()
        self._cover_token = token

        def job():
            try:
                img = image_fn()
            except Exception:
                img = None
            QTimer.singleShot(0, self, lambda: self._cover_loaded(token, img))

        self.covers.submit(job)

    def _cover_loaded(self, token, img):
        if token is not getattr(self, "_cover_token", None):
            return
        self.cover.set_image(img)
        color = dominant_color(img) if img is not None else None
        self.hero.color = color or QColor(theme.RED_DARK)
        self.hero.update()

    def _on_meta_link(self):
        pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if getattr(self, "_title_text", ""):
            self._fit_title(self._title_text)


class AlbumPage(DetailPage):
    def __init__(self, covers, is_playing_fn, parent=None):
        super().__init__(covers, is_playing_fn, "album", parent)
        self.table = self._table((COL_NUM, COL_TITLE, COL_PLAYS, COL_FORMAT, COL_TIME))
        self.footer = QLabel("")
        self.footer.setStyleSheet(f"color: {theme.DIM}; font-size: 12px; padding: 14px 32px 0 32px;")
        self.body.addWidget(self.footer)
        self.more_label = self._section(tr("More by this artist"))
        self.more_grid = self._grid(False, True)
        self.body.addStretch(1)
        self.album = None
        covers.album_art_ready.connect(self._on_album_art)

    def _on_album_art(self, key):
        """Show the official cover as soon as it has been downloaded."""
        if self.album is not None and key == self.album.key and self.isVisible():
            album = self.album
            self._load_cover(lambda: self.covers.album_image(album))

    def show_album(self, album, collection):
        self.album = album
        self.tracks = list(album.tracks)
        self._title_text = theme.title_text(album.title)
        self._fit_title(self._title_text)
        self.meta_link.setText(album.artist)
        parts = [album.year] if album.year else []
        parts.append(n_songs(len(album.tracks)) + ", " + duration_long(album.duration))
        self.meta.setText("  •  " + "  •  ".join(parts))
        self.table.model_.set_tracks(self.tracks)
        plays = sum(t.plays for t in album.tracks)
        self.footer.setText((album.genre + "  ·  " if album.genre else "") + n_times(plays))
        artist = collection.artist_named(album.artist) if collection else None
        others = [a for a in (artist.albums if artist else []) if a.key != album.key]
        self.more_label.setText(theme.title_text(tr("More by {artist}", artist=album.artist)))
        self.more_label.setVisible(bool(others))
        self.more_grid.set_items(others)
        self.more_grid.parentWidget().setVisible(bool(others))
        self.hero.color = QColor(theme.RED_DARK)
        self.cover.set_image(None)
        self._load_cover(lambda: self.covers.album_image(album))
        self.verticalScrollBar().setValue(0)

    def _on_meta_link(self):
        if self.album is not None:
            self.open_artist.emit(self.album.artist)


class ArtistPage(DetailPage):
    def __init__(self, covers, is_playing_fn, parent=None):
        super().__init__(covers, is_playing_fn, "artist", parent)
        self._section(tr("Popular"))
        self.popular = self._table((COL_NUM, COL_TITLE, COL_PLAYS, COL_TIME))
        self.albums_label = self._section(tr("Albums"))
        self.albums_grid = self._grid(False, False)
        self.albums_grid.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.albums_grid.wheelEvent = lambda e: e.ignore()
        self._section(tr("All songs"))
        self.all_songs = self._table((COL_NUM, COL_TITLE, COL_ALBUM, COL_PLAYS, COL_TIME))
        self.body.addStretch(1)
        self.artist = None
        covers.album_art_ready.connect(self._on_picture)

    def _on_picture(self, key):
        """Show the downloaded photo as soon as it arrives."""
        if self.artist is not None and key == "artist:" + self.artist.key and self.isVisible():
            artist = self.artist
            self._load_cover(lambda: self.covers.artist_image(artist))

    def show_artist(self, artist):
        self.artist = artist
        self.tracks = list(artist.tracks)
        self._title_text = theme.title_text(artist.name)
        self._fit_title(self._title_text)
        self.meta_link.setText("")
        self.meta.setText("  •  ".join(x for x in (
            n_songs(len(artist.tracks)), n_albums(len(artist.albums)) if artist.albums else "",
            n_times(artist.plays) if artist.plays else "") if x))
        popular = sorted(artist.tracks, key=lambda t: (-t.plays, t.title.casefold()))[:5]
        self.popular.model_.set_tracks(popular)
        self.all_songs.model_.set_tracks(self.tracks)
        self.albums_grid.set_items(artist.albums)
        self.albums_label.setVisible(bool(artist.albums))
        self.albums_grid.parentWidget().setVisible(bool(artist.albums))
        QTimer.singleShot(0, self._fit_albums)
        self.hero.color = QColor(theme.RED_DARK)
        self.cover.set_image(None)
        self._load_cover(lambda: self.covers.artist_image(artist))
        self.verticalScrollBar().setValue(0)

    def _fit_albums(self):
        grid = self.albums_grid
        n = grid.model_.rowCount()
        if not n:
            return
        cols = grid._columns()
        rows = (n + cols - 1) // cols
        grid.setFixedHeight(rows * grid.gridSize().height() + 8)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_albums()
