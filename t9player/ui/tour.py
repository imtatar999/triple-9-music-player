"""First-run tour: a little animated mascot (dreads, 999 chain) walks through the main features.

Shown once after a fresh install - never after an update - and can be skipped at any moment.
"""

import math

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
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
        s = self.width() / 100.0
        p.scale(s, s)
        t = self._t
        bob = math.sin(t * 3.0) * 2.0
        p.translate(0, bob)
        skin, ink = QColor("#9a6a48"), QColor("#0e0b0a")
        hair, tips = QColor("#2b1d16"), QColor("#d2a565")
        suit, shirt = QColor("#2a2a2f"), QColor("#f2f2f2")
        pen = QPen(ink, 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        # shadow
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 70))
        p.drawEllipse(QPointF(50, 113 - bob), 25 - bob, 4.5)
        # dreads hanging behind the head and shoulders
        for i in range(8):
            x = 30 + i * 5.7
            sway = math.sin(t * 2.2 + i * 0.8) * 1.8
            length = 26 + (i % 3) * 5
            p.setPen(QPen(ink, 6.5, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(x, 30), QPointF(x + sway, 30 + length))
            p.setPen(QPen(hair, 4.6, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(x, 30), QPointF(x + sway, 30 + length - 6))
            p.setPen(QPen(tips, 4.6, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(x + sway * 0.8, 30 + length - 6), QPointF(x + sway, 30 + length))
        # suit jacket with lapels, white shirt and a black tie
        body = QPainterPath()
        body.moveTo(20, 114)
        body.cubicTo(20, 84, 32, 74, 50, 74)
        body.cubicTo(68, 74, 80, 84, 80, 114)
        body.closeSubpath()
        p.setPen(pen)
        p.setBrush(suit)
        p.drawPath(body)
        shirt_path = QPainterPath()
        shirt_path.moveTo(42, 75)
        shirt_path.lineTo(50, 98)
        shirt_path.lineTo(58, 75)
        shirt_path.closeSubpath()
        p.setBrush(shirt)
        p.drawPath(shirt_path)
        tie = QPainterPath()
        tie.moveTo(48, 77)
        tie.lineTo(52, 77)
        tie.lineTo(53.5, 95)
        tie.lineTo(50, 99)
        tie.lineTo(46.5, 95)
        tie.closeSubpath()
        p.setBrush(ink)
        p.drawPath(tie)
        p.setBrush(QColor("#1d1d22"))
        for side in (-1, 1):
            lapel = QPainterPath()
            lapel.moveTo(50 + side * 8, 75)
            lapel.lineTo(50 + side * 2, 96)
            lapel.lineTo(50 + side * 14, 84)
            lapel.closeSubpath()
            p.drawPath(lapel)
        # waving hand in a suit sleeve
        wave = math.sin(t * 6.0) * 14
        p.save()
        p.translate(75, 88)
        p.rotate(-45 + wave)
        p.setBrush(suit)
        p.drawRoundedRect(QRectF(0, -5.5, 22, 11), 5, 5)
        p.setBrush(shirt)
        p.drawRect(QRectF(20, -4.5, 3, 9))
        p.setBrush(skin)
        p.drawEllipse(QPointF(26, 0), 5, 5)
        p.restore()
        # neck + face
        p.setBrush(skin)
        p.drawRect(QRectF(45, 62, 10, 12))
        p.drawEllipse(QPointF(50, 46), 19, 21)
        # round black sunglasses with a little glint
        p.setPen(QPen(QColor("#b9b9c0"), 1.4))
        p.drawLine(QPointF(47, 47), QPointF(53, 47))
        p.setPen(pen)
        p.setBrush(QColor("#121216"))
        for ex in (42, 58):
            p.drawEllipse(QPointF(ex, 48), 6.2, 6.2)
        glint = 0.5 + 0.5 * math.sin(t * 1.7)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, int(120 + 100 * glint)))
        for ex in (40, 56):
            p.drawEllipse(QPointF(ex, 46), 1.6, 1.6)
        # small calm mouth
        p.setPen(QPen(ink, 1.4))
        p.drawLine(QPointF(48, 59), QPointF(52, 59))
        # fringe: dreads falling over the forehead, tan tips
        for i in range(8):
            x = 33 + i * 4.9
            sway = math.sin(t * 2.2 + i * 0.6) * 1.2
            end = 38 + (i % 3) * 3
            p.setPen(QPen(ink, 6, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(x, 24), QPointF(x + sway, end))
            p.setPen(QPen(hair, 4.2, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(x, 24), QPointF(x + sway, end - 5))
            p.setPen(QPen(tips, 4.2, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(x + sway * 0.8, end - 5), QPointF(x + sway, end))
        # top of the hair
        p.setPen(pen)
        p.setBrush(hair)
        top = QPainterPath()
        top.moveTo(30, 34)
        top.cubicTo(30, 18, 40, 13, 50, 13)
        top.cubicTo(60, 13, 70, 18, 70, 34)
        top.cubicTo(62, 26, 38, 26, 30, 34)
        p.drawPath(top)


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
        candidates = [(bx - mw + 12, by + bh - mh // 2), (bx + bw - 12, by + bh - mh // 2),
                      (bx - mw + 12, by - mh // 2), (bx + bw - 12, by - mh // 2),
                      (bx + bw // 2 - mw // 2, by - mh + 10), (bx + bw // 2 - mw // 2, by + bh - 10)]
        for mx, my in candidates:
            spot = QRect(int(mx), int(my), mw, mh)
            if self.rect().contains(spot) and (r.isNull() or not spot.intersects(r.adjusted(-8, -8, 8, 8))):
                break
        self.mascot.move(int(mx), int(my))
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
