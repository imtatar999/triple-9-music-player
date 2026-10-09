"""First-run tour: a little animated mascot (dreads, 999 chain) walks through the main features.

Shown once after a fresh install - never after an update - and can be skipped at any moment.
"""

import math

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .. import theme
from ..i18n import tr


class Mascot(QWidget):
    """A small cartoon with dreadlocks that bobs, blinks and waves."""

    def __init__(self, parent=None, size=120):
        super().__init__(parent)
        self.setFixedSize(size, int(size * 1.15))
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._t = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._step)
        self._timer.start()

    def _step(self):
        self._t += 0.033
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        s = w / 100.0
        p.scale(s, s)
        t = self._t
        bob = math.sin(t * 3.0) * 2.5
        p.translate(0, bob)
        skin, ink = QColor("#8a5a3c"), QColor("#140d0a")
        # shadow
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 70))
        p.drawEllipse(QPointF(50, 112 - bob), 26 - bob, 5)
        # body: black hoodie
        body = QPainterPath()
        body.moveTo(22, 112)
        body.cubicTo(22, 82, 34, 74, 50, 74)
        body.cubicTo(66, 74, 78, 82, 78, 112)
        body.closeSubpath()
        p.setBrush(QColor("#1b1b20"))
        p.setPen(QPen(ink, 2))
        p.drawPath(body)
        # 999 chain
        p.setPen(QPen(QColor("#e8c46a"), 2))
        p.setBrush(Qt.NoBrush)
        p.drawArc(QRectF(36, 70, 28, 20), 200 * 16, 140 * 16)
        p.setPen(QColor(theme.RED_BRIGHT))
        f = QFont("Segoe UI", 1)
        f.setPixelSize(8)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(38, 86, 24, 10), Qt.AlignCenter, "999")
        # waving arm
        wave = math.sin(t * 6.0) * 14
        p.save()
        p.translate(74, 86)
        p.rotate(-40 + wave)
        p.setPen(QPen(ink, 2))
        p.setBrush(QColor("#1b1b20"))
        p.drawRoundedRect(QRectF(0, -5, 22, 10), 5, 5)
        p.setBrush(skin)
        p.drawEllipse(QPointF(24, 0), 5, 5)
        p.restore()
        # dreads behind the head
        for i in range(9):
            x = 26 + i * 6
            sway = math.sin(t * 2.5 + i) * 2
            length = 22 + (i % 3) * 4
            p.setPen(QPen(ink, 5, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(x, 30), QPointF(x + sway, 30 + length))
            tip = QColor("#e8b04a") if i % 2 else QColor(theme.RED_BRIGHT)
            p.setPen(QPen(tip, 5, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(x + sway * 0.8, 30 + length - 4), QPointF(x + sway, 30 + length))
        # head
        p.setPen(QPen(ink, 2))
        p.setBrush(skin)
        p.drawEllipse(QPointF(50, 44), 21, 22)
        # dreads on top (fringe)
        for i in range(7):
            x = 33 + i * 5.7
            sway = math.sin(t * 2.5 + i * 0.7) * 1.5
            p.setPen(QPen(ink, 5, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(x, 25), QPointF(x + sway, 38 + (i % 2) * 4))
        # eyes (blink every few seconds)
        blink = (t % 3.6) < 0.12
        p.setPen(QPen(ink, 2))
        p.setBrush(ink)
        for ex in (43, 57):
            if blink:
                p.drawLine(QPointF(ex - 3, 48), QPointF(ex + 3, 48))
            else:
                p.drawEllipse(QPointF(ex, 48), 2.4, 2.8)
        # smile
        p.setBrush(Qt.NoBrush)
        p.drawArc(QRectF(43, 50, 14, 9), 200 * 16, 140 * 16)


class TourOverlay(QWidget):
    """Dims the window, highlights one control at a time and explains it in a speech bubble."""
    finished = Signal()

    def __init__(self, window, steps):
        super().__init__(window)
        self.window_ = window
        self.steps = steps          # [(widget or None, title, text)]
        self.index = 0
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setGeometry(window.rect())
        self.mascot = Mascot(self, 110)
        self.bubble = QWidget(self)
        self.bubble.setObjectName("TourBubble")
        self.bubble.setStyleSheet(
            f"#TourBubble {{ background: {theme.RAISED}; border: 1px solid {theme.RED}; border-radius: 14px; }}")
        lay = QVBoxLayout(self.bubble)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(6)
        self.title = QLabel("")
        self.title.setStyleSheet(f"color: {theme.TEXT}; font-size: 17px; font-weight: 700; background: transparent;")
        self.text = QLabel("")
        self.text.setWordWrap(True)
        self.text.setStyleSheet(f"color: {theme.DIM}; font-size: 13px; background: transparent;")
        self.counter = QLabel("")
        self.counter.setStyleSheet(f"color: {theme.FAINT}; font-size: 11px; background: transparent;")
        row = QHBoxLayout()
        self.skip = QPushButton(tr("Skip"))
        self.skip.setToolTip(tr("Close the tour - you can find everything yourself"))
        self.next = QPushButton(tr("Next"))
        self.next.setObjectName("Primary")
        self.next.setToolTip(tr("Show the next tip"))
        for b in (self.skip, self.next):
            b.setCursor(Qt.PointingHandCursor)
        self.skip.clicked.connect(self.close_tour)
        self.next.clicked.connect(self.advance)
        row.addWidget(self.counter)
        row.addStretch(1)
        row.addWidget(self.skip)
        row.addWidget(self.next)
        lay.addWidget(self.title)
        lay.addWidget(self.text)
        lay.addLayout(row)
        self.bubble.setFixedWidth(360)
        window.installEventFilter(self)
        self._show_step()

    # ------------------------------------------------------------------ steps
    def _target_rect(self):
        widget = self.steps[self.index][0]
        if widget is None or not widget.isVisible():
            return QRect()
        top_left = widget.mapTo(self.window_, widget.rect().topLeft())
        return QRect(top_left, widget.size()).adjusted(-6, -6, 6, 6)

    def _show_step(self):
        _, title, text = self.steps[self.index]
        self.title.setText(title)
        self.text.setText(text)
        last = self.index == len(self.steps) - 1
        self.next.setText(tr("Let's go!") if last else tr("Next"))
        self.skip.setVisible(not last)
        self.counter.setText(f"{self.index + 1} / {len(self.steps)}")
        self.bubble.adjustSize()
        self._place()
        self.update()

    def _place(self):
        self.setGeometry(self.window_.rect())
        r = self._target_rect()
        bw, bh = self.bubble.width(), self.bubble.sizeHint().height()
        mw, mh = self.mascot.width(), self.mascot.height()
        W, H = self.width(), self.height()
        if r.isNull():
            bx, by = (W - bw) // 2 + mw // 2, (H - bh) // 2
        else:
            bx = r.right() + 24 if r.right() + 24 + bw + 10 < W else r.left() - bw - 24
            if bx < 10:
                bx = max(10, min(W - bw - 10, r.center().x() - bw // 2))
                by = r.top() - bh - 24 if r.top() - bh - 24 > 10 else r.bottom() + 24
            else:
                by = max(10, min(H - bh - mh - 10, r.center().y() - bh // 2))
        self.bubble.move(bx, by)
        mx = bx - mw + 12 if bx - mw + 12 > 0 else bx + bw - mw // 2
        self.mascot.move(mx, by + bh - mh // 2)
        self.bubble.raise_()

    def advance(self):
        if self.index >= len(self.steps) - 1:
            self.close_tour()
            return
        self.index += 1
        self._show_step()

    def close_tour(self):
        self.window_.removeEventFilter(self)
        self.hide()
        self.finished.emit()
        self.deleteLater()

    def eventFilter(self, obj, event):
        if obj is self.window_ and event.type() == event.Type.Resize:
            self._place()
        return False

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close_tour()
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Right, Qt.Key_Space):
            self.advance()

    def mousePressEvent(self, event):
        event.accept()          # clicks on the dimmed area do nothing

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dim = QPainterPath()
        dim.addRect(QRectF(self.rect()))
        r = self._target_rect()
        if not r.isNull():
            hole = QPainterPath()
            hole.addRoundedRect(QRectF(r), 12, 12)
            dim = dim.subtracted(hole)
        p.fillPath(dim, QColor(0, 0, 0, 165))
        if not r.isNull():
            p.setPen(QPen(QColor(theme.RED_BRIGHT), 2.5))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(r), 12, 12)
