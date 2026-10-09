"""Full lyrics view: cover on one half, synced lyrics on the other, blurred backdrop."""

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .. import theme
from ..i18n import tr
from .decor import GothicNight, MatrixRain, lyrics_background, paint_lyrics
from .lyrics_view import LyricsView
from .widgets import CoverWidget, ElidedLabel, IconButton


class LyricsPage(QWidget):
    back_requested = Signal()
    fullscreen_requested = Signal()
    font_step = Signal(int)
    offset_step = Signal(float)
    swap_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self._backdrop = None
        self._backdrop_scaled = None
        self._cover_side = "left"

        # Matrix: falling code behind everything (created first = drawn first)
        self.rain = MatrixRain(self) if theme.DECOR == "rain" else None
        if theme.DECOR == "gothic":
            self.rain = GothicNight(self)       # moon, clouds, bats, hearts (and rain on some songs)
            self.rain.reroll()
        self._overlay = None
        self.cover = CoverWidget(radius=14, shadow=True)
        self.title = ElidedLabel("")
        self.title.setStyleSheet(f"color: {theme.TEXT}; {theme.title_css(26)}")
        self.artist = ElidedLabel("")
        self.artist.setStyleSheet(f"color: {theme.DIM}; font-size: 15px;")
        self.source = QLabel("")
        self.source.setStyleSheet(f"color: {theme.FAINT}; font-size: 11px;")
        cover_box = QWidget()
        cb = QVBoxLayout(cover_box)
        cb.setContentsMargins(0, 0, 0, 0)
        cb.setSpacing(6)
        cb.addStretch(1)
        cb.addWidget(self.cover, 10)
        cb.addSpacing(14)
        cb.addWidget(self.title)
        cb.addWidget(self.artist)
        cb.addWidget(self.source)
        cb.addStretch(1)
        self.cover_box = cover_box

        self.view = LyricsView(self)
        self.row = QHBoxLayout()
        self.row.setContentsMargins(56, 56, 24, 24)
        self.row.setSpacing(40)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addLayout(self.row)
        self._place()

        # floating toolbar (top-right)
        self.toolbar = QWidget(self)
        tl = QHBoxLayout(self.toolbar)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(2)
        self.btn_back = IconButton("back", tr("Back to the library (Esc)"), 34, 20)
        self.btn_smaller = IconButton("text_minus", tr("Smaller lyrics text (Ctrl+-)"), 34, 20)
        self.btn_bigger = IconButton("text_plus", tr("Bigger lyrics text (Ctrl+=)"), 34, 20)
        self.btn_earlier = IconButton("minus", tr("Lyrics too late? Show them earlier by 0.1 s ([)"), 34, 18)
        self.offset_label = QLabel("0.0 s")
        self.offset_label.setStyleSheet(f"color: {theme.DIM}; font-size: 11px;")
        self.offset_label.setToolTip(tr("Lyrics timing offset for this song (saved)"))
        self.offset_label.setFixedWidth(44)
        self.offset_label.setAlignment(Qt.AlignCenter)
        self.btn_later = IconButton("add", tr("Lyrics too early? Show them later by 0.1 s (])"), 34, 18)
        self.btn_swap = IconButton("swap", tr("Move the cover to the other side"), 34, 20)
        self.btn_full = IconButton("fullscreen", tr("Full screen (F11)"), 34, 20)
        for w in (self.btn_back, self.btn_smaller, self.btn_bigger, self.btn_earlier,
                  self.offset_label, self.btn_later, self.btn_swap, self.btn_full):
            tl.addWidget(w)
        for b in (self.btn_back, self.btn_smaller, self.btn_bigger, self.btn_earlier,
                  self.btn_later, self.btn_swap, self.btn_full):
            b.set_colors(normal="#b9b9c0")
        self.btn_back.clicked.connect(self.back_requested)
        self.btn_full.clicked.connect(self.fullscreen_requested)
        self.btn_smaller.clicked.connect(lambda: self.font_step.emit(-2))
        self.btn_bigger.clicked.connect(lambda: self.font_step.emit(2))
        self.btn_earlier.clicked.connect(lambda: self.offset_step.emit(0.1))
        self.btn_later.clicked.connect(lambda: self.offset_step.emit(-0.1))
        self.btn_swap.clicked.connect(self.swap_requested)
        self.toolbar.adjustSize()

    # ------------------------------------------------------------------ content
    def set_track(self, track):
        if track is None:
            self.title.setText(theme.title_text(theme.say("Nothing playing")))
            self.artist.setText("")
        else:
            self.title.setText(theme.title_text(track.title))
            if isinstance(self.rain, GothicNight):
                self.rain.reroll()
            self.artist.setText(track.display_artist + (f" • {track.album}" if track.album else ""))

    def set_cover(self, cover, blurred):
        self.cover.set_image(cover)
        self._backdrop = QPixmap.fromImage(blurred) if blurred is not None else None
        self._backdrop_scaled = None
        self.update()

    def set_source(self, text):
        self.source.setText(text)

    def set_offset_text(self, offset):
        # positive offset = lyrics earlier
        self.offset_label.setText(f"{offset:+.1f} s" if abs(offset) >= 0.05 else "0.0 s")

    def set_rain(self, on):
        if isinstance(self.rain, MatrixRain):
            self.rain.setVisible(bool(on))

    def set_cover_side(self, side):
        if side != self._cover_side:
            self._cover_side = side
            self._place()
            if isinstance(self.rain, GothicNight):
                self.rain.cover_side = side

    def set_fullscreen_icon(self, full):
        self.btn_full.set_icon("fullscreen_exit" if full else "fullscreen")
        self.btn_full.setToolTip(tr("Leave full screen (F11 / Esc)") if full else tr("Full screen (F11)"))

    def _place(self):
        while self.row.count():
            self.row.takeAt(0)
        if self._cover_side == "left":
            self.row.addWidget(self.cover_box, 9)
            self.row.addWidget(self.view, 11)
        else:
            self.row.addWidget(self.view, 11)
            self.row.addWidget(self.cover_box, 9)

    # ------------------------------------------------------------------ painting
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._backdrop_scaled = None
        self._overlay = None
        w, h = self.width(), self.height()
        self.toolbar.adjustSize()
        self.toolbar.move(w - self.toolbar.width() - 14, 10)
        self.toolbar.raise_()
        # scale paddings with the window so full screen breathes
        pad = int(max(24, min(90, w * 0.045)))
        self.row.setContentsMargins(pad, max(56, int(h * 0.07)), int(pad * 0.5), max(24, int(h * 0.04)))
        self.row.setSpacing(int(max(24, min(80, w * 0.035))))
        self.view.set_size_factor(max(0.75, min(1.6, h / 820)))
        self.title.setStyleSheet(f"color: {theme.TEXT}; {theme.title_css(int(max(18, min(34, h * 0.03))))}")
        if self.rain is not None:
            self.rain.setGeometry(self.rect())
            self.rain.lower()

    def paintEvent(self, event):
        p = QPainter(self)
        r = self.rect()
        p.fillRect(r, QColor(theme.BG))
        if self._backdrop is not None and not self._backdrop.isNull():
            if self._backdrop_scaled is None or self._backdrop_scaled.size() != r.size():
                self._backdrop_scaled = self._backdrop.scaled(
                    r.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            bs = self._backdrop_scaled
            p.drawPixmap((r.width() - bs.width()) // 2, (r.height() - bs.height()) // 2, bs)
        else:
            lyrics_background(p, r)
        # darken the lyrics half for contrast
        shade = QLinearGradient(0, 0, r.width(), 0)
        dark = QColor(0, 0, 0, 150)
        clear = QColor(0, 0, 0, 40)
        if self._cover_side == "left":
            shade.setColorAt(0, clear)
            shade.setColorAt(0.5, QColor(0, 0, 0, 110))
            shade.setColorAt(1, dark)
        else:
            shade.setColorAt(0, dark)
            shade.setColorAt(0.5, QColor(0, 0, 0, 110))
            shade.setColorAt(1, clear)
        p.fillRect(r, shade)
        if self._overlay is None or self._overlay.size() != r.size():
            self._overlay = QPixmap(r.size())
            self._overlay.fill(Qt.transparent)
            q = QPainter(self._overlay)
            paint_lyrics(q, QRectF(r))
            q.end()
        p.drawPixmap(0, 0, self._overlay)
        vignette = QLinearGradient(0, r.height() - 120, 0, r.height())
        vignette.setColorAt(0, QColor(0, 0, 0, 0))
        vignette.setColorAt(1, QColor(0, 0, 0, 120))
        p.fillRect(QRectF(0, r.height() - 120, r.width(), 120), vignette)
