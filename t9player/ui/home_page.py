"""Home: the theme's logo and story, your top artists, most played songs and a few shortcuts."""

import random
import time

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from .. import icons, theme
from ..i18n import albums as n_albums, duration_long, language, plural, songs as n_songs, times as n_times, tr
from .collection_view import TileGrid
from .library_view import COL_ALBUM, COL_NUM, COL_PLAYS, COL_TIME, COL_TITLE, TrackTable
from .widgets import BrandLabel

# two sentences about what each theme stands for (English keys, Polish in i18n_pl.py)
ABOUT = {
    "999": ("999 EP - Juice WRLD's first EP, released on SoundCloud on June 15, 2017.",
            "999 is 666 turned upside down: take whatever bad you go through and turn it into something good."),
    "gbgr": ("Goodbye & Good Riddance - Juice WRLD's debut album, released on May 23, 2018.",
             "It has “Lucid Dreams” and “All Girls Are the Same”, the songs that made him famous."),
    "wod": ("WRLD On Drugs - a joint mixtape of Juice WRLD and Future, released on October 19, 2018.",
            "It debuted at number 2 on the Billboard 200."),
    "drfl": ("Death Race for Love - Juice WRLD's second album, released on March 8, 2019.",
             "It was his first album to debut at number 1 on the Billboard 200."),
    "tpne": ("The Party Never Ends - Juice WRLD's final posthumous album, released on November 29, 2024.",
             "Its cover was designed by Takashi Murakami, who also made the cover of Kanye West's Graduation."),
    "outsiders": ("The Outsiders - in May 2020 this was announced as the title of Juice WRLD's first posthumous album.",
                  "In the end the album came out in July 2020 as Legends Never Die."),
    "lnd": ("Legends Never Die - Juice WRLD's first posthumous album, released on July 10, 2020.",
            "It debuted at number 1 on the Billboard 200 and put five of its songs in the Hot 100 top 10 in one week."),
}

TOP_SONGS = 10


def _part_of_day(hour):
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 18:
        return "afternoon"
    if 18 <= hour < 23:
        return "evening"
    return "night"


def _daily(items, salt=0):
    """The same pick all day, a different one tomorrow."""
    return items[(time.localtime().tm_yday + salt) % len(items)]


# greetings in the spirit of Juice WRLD's songs (English on purpose: they play on his titles)
GREETINGS = {
    "morning": ("Rise and shine - new day, new dreams", "Good morning, legend",
                "Wake up - no more lucid dreams, time for real ones", "Morning! Let's start the day on a high note"),
    "afternoon": ("Afternoon, legend - legends never die", "Hope your day is going righteous"),
    "evening": ("Good evening - welcome to the WRLD", "Evening, 999 - what are we playing tonight?",
                "Night drive vibes - fasten your seatbelt", "Wishing you a good night, and a good playlist"),
    "night": ("Still up? Lucid dreams time", "3 AM and the music hits different",
              "Can't sleep? Let it all out in the music", "Good night - 999 forever"),
}


def greeting():
    hour = time.localtime().tm_hour
    greetings = theme.extra("greetings")
    if greetings:
        return tr(_daily(greetings[_part_of_day(hour)]))
    return _daily(GREETINGS[_part_of_day(hour)])


class HomePage(QScrollArea):
    play_tracks = Signal(list, int)
    play_toggle = Signal(list, int)
    shuffle_tracks = Signal(list)
    open_item = Signal(object)
    play_item = Signal(object)
    item_menu = Signal(object, QPoint)
    track_menu = Signal(object, QPoint)
    show_view = Signal(str)               # "most", "history", "favorites" ...

    def __init__(self, covers, is_playing_fn, parent=None):
        super().__init__(parent)
        self.covers = covers
        self._is_playing = is_playing_fn
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
        self._all = []
        self._collection = None

        # ---- the theme: logo, name and what it stands for
        self.body.addSpacing(34)
        row = QHBoxLayout()
        row.addStretch(1)
        if theme.BRAND == "cat":
            row.addWidget(BrandLabel(height=120, text_size=54, spacing=20))
        else:
            row.addWidget(BrandLabel(height=72, text_size=42, spacing=16))
        row.addStretch(1)
        self.body.addLayout(row)
        self.body.addSpacing(14)
        name = QLabel(theme.title_text(theme.label))
        name.setAlignment(Qt.AlignCenter)
        name.setStyleSheet(f"color: {theme.RED_BRIGHT}; {theme.title_css(30)}")
        self.body.addWidget(name)
        quote, line = theme.extra("home_quote"), theme.extra("home_line")
        if line:
            # decorative fonts may have no "<": the last word (a heart) is drawn in the normal font
            text, heart = line.rsplit(" ", 1)
            about = (f"<div style=\"font-size: {int(19 * theme.TITLE_SCALE)}px; color: {theme.DIM};\">"
                     f"&quot;{theme.title_text(quote or '')}&quot;</div>"
                     f"<div style=\"margin-top: 8px;\">{theme.title_text(text)} "
                     f"<span style=\"font-family: '{theme.FONT}'; font-weight: 800; "
                     f"color: {theme.RED_BRIGHT};\">{heart.replace('<', '&lt;')}</span></div>")
            style = f"color: {theme.TEXT}; {theme.title_css(26)}"
        elif quote:
            about = f"\"{theme.title_text(quote)}\""
            style = f"color: {theme.TEXT}; {theme.title_css(24)}"
        else:
            about = " ".join(tr(s) for s in (theme.extra("about") or ABOUT.get(theme.NAME, ())))
            style = f"color: {theme.DIM}; font-size: 14px;"
        self.about = QLabel(about)
        self.about.setAlignment(Qt.AlignCenter)
        self.about.setWordWrap(True)
        self.about.setStyleSheet(style + " padding: 6px 0;")
        self.about.setMaximumWidth(680)
        wrap = QHBoxLayout()
        wrap.addStretch(1)
        wrap.addWidget(self.about, 4)
        wrap.addStretch(1)
        self.body.addLayout(wrap)

        # ---- greeting, numbers and quick actions
        self.body.addSpacing(18)
        self.hello = QLabel("")
        self.hello.setStyleSheet(f"color: {theme.TEXT}; {theme.title_css(34)} padding: 10px 32px 0 32px;")
        self.body.addWidget(self.hello)
        self.stats = QLabel("")
        self.stats.setStyleSheet(f"color: {theme.DIM}; font-size: 13px; padding: 2px 32px 0 32px;")
        self.stats.setWordWrap(True)
        self.body.addWidget(self.stats)
        if theme.extra("notes"):
            note = QLabel("♥  " + tr(_daily(theme.extra("notes"), 3)))
            note.setWordWrap(True)
            note.setStyleSheet(f"color: {theme.RED_BRIGHT}; font-size: 14px; font-style: italic; "
                               "padding: 8px 32px 0 32px;")
            self.body.addWidget(note)
        actions = QHBoxLayout()
        actions.setContentsMargins(32, 14, 32, 4)
        actions.setSpacing(10)
        self.shuffle_btn = QPushButton("  " + tr("Shuffle everything"))
        self.shuffle_btn.setObjectName("Primary")
        self.shuffle_btn.setIcon(icons.icon("shuffle", theme.ON_ACCENT, 16))
        self.shuffle_btn.setToolTip(tr("Play the whole library in random order"))
        self.shuffle_btn.clicked.connect(lambda: self.shuffle_tracks.emit(list(self._all)))
        self.top_btn = QPushButton("  " + tr("Play your top songs"))
        self.top_btn.setIcon(icons.icon("fire", theme.TEXT, 16))
        self.top_btn.setToolTip(tr("Play your most played songs from the top"))
        self.top_btn.clicked.connect(self._play_top)
        self.lucky_btn = QPushButton("  " + tr("Surprise me"))
        self.lucky_btn.setIcon(icons.icon("album", theme.TEXT, 16))
        self.lucky_btn.setToolTip(tr("Play a random album from your library"))
        self.lucky_btn.clicked.connect(self._surprise)
        for b in (self.shuffle_btn, self.top_btn, self.lucky_btn):
            b.setCursor(Qt.PointingHandCursor)
            actions.addWidget(b)
        actions.addStretch(1)
        self.body.addLayout(actions)

        # ---- sections
        self.artists_label = self._section(tr("Your top artists"))
        self.artists_grid = self._grid(round_art=True)
        self.songs_label = self._section(tr("Most played songs"), "most")
        self.songs = TrackTable(covers, is_playing_fn, embedded=True)
        self.songs.set_visible_columns((COL_NUM, COL_TITLE, COL_ALBUM, COL_PLAYS, COL_TIME))
        self._wrap(self.songs, 24)
        self.songs.activated_row.connect(lambda r: self.play_tracks.emit(self.songs.model_.tracks(), r))
        self.songs.play_clicked.connect(lambda r: self.play_toggle.emit(self.songs.model_.tracks(), r))
        self.songs.context_requested.connect(lambda pos: self.track_menu.emit(self.songs, pos))
        self.albums_label = self._section(tr("Albums on repeat"))
        self.albums_grid = self._grid()
        self.recent_label = self._section(tr("Jump back in"), "history")
        self.recent_grid = self._grid()
        self.new_label = self._section(tr("Recently added"), "recent")
        self.new_grid = self._grid()
        self.forgot_label = self._section(tr("Haven't heard these in a while"))
        self.forgot = TrackTable(covers, is_playing_fn, embedded=True)
        self.forgot.set_visible_columns((COL_NUM, COL_TITLE, COL_ALBUM, COL_PLAYS, COL_TIME))
        self._wrap(self.forgot, 24)
        self.forgot.activated_row.connect(lambda r: self.play_tracks.emit(self.forgot.model_.tracks(), r))
        self.forgot.play_clicked.connect(lambda r: self.play_toggle.emit(self.forgot.model_.tracks(), r))
        self.forgot.context_requested.connect(lambda pos: self.track_menu.emit(self.forgot, pos))
        self.empty = QLabel(tr("Play some music and your favourites will show up here."))
        self.empty.setStyleSheet(f"color: {theme.FAINT}; font-size: 13px; padding: 18px 32px;")
        self.body.addWidget(self.empty)
        self.body.addStretch(1)

    # ------------------------------------------------------------------ building blocks
    def _section(self, text, view=None):
        row = QHBoxLayout()
        row.setContentsMargins(32, 22, 32, 6)
        lab = QLabel(theme.title_text(text))
        lab.setStyleSheet(f"color: {theme.TEXT}; {theme.title_css(22)}")
        row.addWidget(lab)
        row.addStretch(1)
        holder = QWidget()
        holder.setLayout(row)
        if view:
            more = QPushButton(tr("Show all"))
            more.setFlat(True)
            more.setCursor(Qt.PointingHandCursor)
            more.setToolTip(tr("Open the full list"))
            more.setStyleSheet(f"QPushButton {{ color: {theme.DIM}; background: transparent; border: none; "
                               f"font-size: 12px; font-weight: 700; }} QPushButton:hover {{ color: {theme.TEXT}; }}")
            more.clicked.connect(lambda: self.show_view.emit(view))
            row.addWidget(more, 0, Qt.AlignBottom)
        self.body.addWidget(holder)
        return holder

    def _wrap(self, widget, margin):
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(margin, 0, margin, 0)
        wl.addWidget(widget)
        self.body.addWidget(wrap)
        return wrap

    def _grid(self, round_art=False):
        grid = TileGrid(self.covers, round_art=round_art, one_row=True)
        self._wrap(grid, 22)
        grid.open_item.connect(self.open_item)
        grid.play_item.connect(self.play_item)
        grid.item_menu.connect(self.item_menu)
        return grid

    @staticmethod
    def _show(label, widget, items):
        visible = bool(items)
        label.setVisible(visible)
        (widget.parentWidget() or widget).setVisible(visible)

    # ------------------------------------------------------------------ content
    def set_data(self, tracks, collection):
        self._all = list(tracks)
        self.hello.setText(theme.title_text(greeting()))
        played = [t for t in self._all if t.plays > 0]
        total_plays = sum(t.plays for t in played)
        listened = sum(t.plays * (t.duration or 0) for t in played)
        n = len(collection.artists)
        artists_text = (plural(n, "wykonawca", "wykonawców", "wykonawców") if language() == "pl"
                        else ("artist" if n == 1 else "artists"))
        parts = [n_songs(len(self._all)), n_albums(len(collection.albums)), f"{n} {artists_text}"]
        if total_plays:
            parts.append(n_times(total_plays))
            parts.append(tr("{time} listened", time=duration_long(listened)))
        self.stats.setText("  •  ".join(parts))
        for b in (self.shuffle_btn, self.lucky_btn):
            b.setEnabled(bool(self._all))
        self.top_btn.setEnabled(bool(played))

        artists = sorted((a for a in collection.artists.values() if a.plays > 0),
                         key=lambda a: (-a.plays, a.name.casefold()))
        self.artists_grid.set_items(artists)
        self._show(self.artists_label, self.artists_grid, artists)

        top = sorted(played, key=lambda t: (-t.plays, -t.last_played))[:TOP_SONGS]
        self.songs.model_.set_tracks(top)
        self._show(self.songs_label, self.songs, top)

        albums = sorted((a for a in collection.albums.values() if a.plays > 0),
                        key=lambda a: (-a.plays, a.title.casefold()))
        self.albums_grid.set_items(albums)
        self._show(self.albums_label, self.albums_grid, albums)

        # albums of the songs played lately, newest first
        last = {}
        for t in self._all:
            if t.last_played > 0:
                album = collection.album_of(t)
                if album is not None and t.last_played > last.get(album.key, (0, None))[0]:
                    last[album.key] = (t.last_played, album)
        recent = [a for _, a in sorted(last.values(), key=lambda x: -x[0])]
        self.recent_grid.set_items(recent)
        self._show(self.recent_label, self.recent_grid, recent)

        newest = sorted(collection.albums.values(), key=lambda a: -max(t.added for t in a.tracks))
        self.new_grid.set_items(newest)
        self._show(self.new_label, self.new_grid, newest)

        # loved once, not played for a month
        month_ago = time.time() - 30 * 86400
        forgotten = sorted((t for t in played if t.plays >= 2 and t.last_played < month_ago),
                           key=lambda t: -t.plays)[:5]
        self.forgot.model_.set_tracks(forgotten)
        self._show(self.forgot_label, self.forgot, forgotten)
        self.empty.setVisible(not played)
        self._collection = collection

    def _play_top(self):
        tracks = self.songs.model_.tracks()
        if tracks:
            top = sorted((t for t in self._all if t.plays > 0), key=lambda t: -t.plays)[:100]
            self.play_tracks.emit(top, 0)

    def _surprise(self):
        albums = list(self._collection.albums.values()) if self._collection else []
        if albums:
            self.play_item.emit(random.choice(albums))

    def tables(self):
        return [self.songs, self.forgot]
