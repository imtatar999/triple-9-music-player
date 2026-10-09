"""Compact player window: big cover (or lyrics), titles, seek bar, transport, volume."""

from PySide6.QtCore import QByteArray, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget

from .. import theme
from ..i18n import tr
from .decor import paint_panel
from .lyrics_view import LyricsView
from .player_bar import Transport, time_label
from .widgets import BrandLabel, CoverWidget, ElidedLabel, IconButton, SeekBar, VolumeSlider, bold_font


class MiniPlayer(QWidget):
    expand_requested = Signal()
    closed = Signal()

    def __init__(self, player, settings, parent=None):
        super().__init__(parent, Qt.Window)
        self.player = player
        self.settings = settings
        self.setWindowTitle(tr("T9 Mini Player"))
        self.setMinimumSize(300, 470)
        self.resize(340, 580)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self._backdrop = None
        self._backdrop_scaled = None
        self._accent = None

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 12, 18, 16)
        root.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(2)
        self.btn_expand = IconButton("expand", tr("Back to the full player (Ctrl+M)"), 32, 18)
        self.btn_lyrics = IconButton("lyrics", tr("Show lyrics instead of the cover (L)"), 32, 18, checkable=True)
        self.btn_pin = IconButton("pin", tr("Keep this window on top of others"), 32, 18, checkable=True)
        top.addWidget(self.btn_expand)
        top.addSpacing(34)      # balances the two buttons on the right so the logo sits centred
        top.addStretch(1)
        top.addWidget(BrandLabel(height=16, text_size=11, spacing=6), 0, Qt.AlignVCenter)
        top.addStretch(1)
        top.addWidget(self.btn_lyrics)
        top.addWidget(self.btn_pin)
        root.addLayout(top)

        self.stack = QStackedWidget()
        self.cover = CoverWidget(radius=12, shadow=True)
        self.cover.setCursor(Qt.PointingHandCursor)
        self.cover.setToolTip(tr("Click to show the lyrics"))
        self.lyrics = LyricsView(size_factor=0.62, compact=True)
        self.stack.addWidget(self.cover)
        self.stack.addWidget(self.lyrics)
        root.addWidget(self.stack, 1)

        titles = QHBoxLayout()
        tbox = QVBoxLayout()
        tbox.setSpacing(0)
        self.title = ElidedLabel(theme.say("Nothing playing"))
        self.title.setFont(bold_font(16, 700))
        self.title.setAlignment(Qt.AlignLeft)
        self.artist = ElidedLabel("")
        self.artist.setStyleSheet(f"color: {theme.DIM}; font-size: 12px;")
        tbox.addWidget(self.title)
        tbox.addWidget(self.artist)
        titles.addLayout(tbox, 1)
        self.heart = IconButton("heart_outline", tr("Add to Favorites (F)"), 32, 18, checkable=True)
        titles.addWidget(self.heart)
        root.addLayout(titles)

        self.seek = SeekBar()
        root.addWidget(self.seek)
        times = QHBoxLayout()
        self.t_pos = time_label(Qt.AlignLeft)
        self.t_dur = time_label(Qt.AlignRight)
        times.addWidget(self.t_pos)
        times.addStretch(1)
        times.addWidget(self.t_dur)
        root.addLayout(times)

        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        self.shuffle = IconButton("shuffle", tr("Shuffle (S)"), 34, 18, checkable=True)
        self.prev = IconButton("prev", tr("Previous / restart (Ctrl+Left)"), 40, 24)
        self.play = IconButton("play", tr("Play (Space)"), 52, 24, filled=True)
        self.next = IconButton("next", tr("Next (Ctrl+Right)"), 40, 24)
        self.repeat = IconButton("repeat", tr("Repeat (R)"), 34, 18, checkable=True)
        buttons.addWidget(self.shuffle)
        buttons.addStretch(1)
        buttons.addWidget(self.prev)
        buttons.addWidget(self.play)
        buttons.addWidget(self.next)
        buttons.addStretch(1)
        buttons.addWidget(self.repeat)
        root.addLayout(buttons)

        vol = QHBoxLayout()
        self.vol_btn = IconButton("volume", tr("Mute (M)"), 30, 18)
        self.volume = VolumeSlider(width=150)
        vol.addStretch(1)
        vol.addWidget(self.vol_btn)
        vol.addWidget(self.volume)
        vol.addStretch(1)
        root.addLayout(vol)

        self.transport = Transport(player, self.play, self.prev, self.next, self.shuffle, self.repeat,
                                   self.seek, self.t_pos, self.t_dur, self.heart, self.volume,
                                   self.vol_btn, self)
        self.btn_expand.clicked.connect(self.expand_requested)
        self.btn_lyrics.toggled.connect(lambda on: self.stack.setCurrentIndex(1 if on else 0))
        self.cover.clicked.connect(lambda: self.btn_lyrics.setChecked(True))
        self.btn_pin.toggled.connect(self._set_on_top)
        self.lyrics.seek_requested.connect(player.seek)
        player.track_changed.connect(self._on_track)
        self._on_track(player.current)
        geo = settings["mini_geometry"]
        if geo:
            try:
                self.restoreGeometry(QByteArray.fromBase64(geo.encode("ascii")))
            except Exception:
                pass
        self.btn_pin.setChecked(bool(settings["mini_on_top"]))

    def _set_on_top(self, on):
        visible = self.isVisible()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, on)
        if visible:
            self.show()
        self.settings.set("mini_on_top", bool(on))

    def _on_track(self, track):
        if track is None:
            self.title.setText(theme.say("Nothing playing"))
            self.artist.setText("")
        else:
            self.title.setText(track.title)
            self.artist.setText(track.display_artist)

    def set_cover(self, cover, blurred):
        self.cover.set_image(cover)
        self._backdrop = QPixmap.fromImage(blurred) if blurred is not None else None
        self._backdrop_scaled = None
        self.update()

    def tick(self):
        if self.isVisible():
            self.transport.tick()

    def save_geometry(self):
        try:
            self.settings.set("mini_geometry", bytes(self.saveGeometry().toBase64()).decode("ascii"))
        except Exception:
            pass

    def closeEvent(self, event):
        self.save_geometry()
        self.closed.emit()
        super().closeEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._backdrop_scaled = None

    def paintEvent(self, event):
        p = QPainter(self)
        r = self.rect()
        p.fillRect(r, QColor(theme.BG))
        if self._backdrop is not None and not self._backdrop.isNull():
            if self._backdrop_scaled is None or self._backdrop_scaled.size() != r.size():
                self._backdrop_scaled = self._backdrop.scaled(r.size(), Qt.KeepAspectRatioByExpanding,
                                                              Qt.SmoothTransformation)
            bs = self._backdrop_scaled
            p.drawPixmap((r.width() - bs.width()) // 2, (r.height() - bs.height()) // 2, bs)
        grad = QLinearGradient(0, 0, 0, r.height())
        grad.setColorAt(0, QColor(10, 4, 6, 120))
        grad.setColorAt(0.55, QColor(8, 6, 8, 185))
        grad.setColorAt(1, QColor(5, 5, 6, 245))
        p.fillRect(r, grad)
        if self._accent is None or self._accent.size() != r.size():
            self._accent = QPixmap(r.size())
            self._accent.fill(Qt.transparent)
            q = QPainter(self._accent)
            q.setOpacity(0.55)
            paint_panel(q, QRectF(r.adjusted(0, 0, 0, -86)))
            q.end()
        p.drawPixmap(0, 0, self._accent)
