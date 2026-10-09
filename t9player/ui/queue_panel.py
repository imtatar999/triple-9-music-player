"""Right-side drawer listing the current song and what plays next."""

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu,
                               QPushButton, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget)

from .. import theme
from ..i18n import tr
from .widgets import fmt_time


class _QueueDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._f1 = QFont(theme.FONT)
        self._f1.setPixelSize(13)
        self._f1.setWeight(QFont.DemiBold)
        self._f2 = QFont(theme.FONT)
        self._f2.setPixelSize(11)

    def sizeHint(self, option, index):
        return QSize(100, 46 if index.data(Qt.UserRole) else 28)

    def paint(self, p, option, index):
        data = index.data(Qt.UserRole)
        r = option.rect
        if not data:
            p.save()
            p.setFont(self._f2)
            p.setPen(QColor(theme.FAINT))
            p.drawText(QRectF(r).adjusted(12, 0, 0, 0), Qt.AlignLeft | Qt.AlignBottom,
                       (index.data(Qt.DisplayRole) or "").upper())
            p.restore()
            return
        track, current = data[1], data[2]
        p.save()
        if option.state & QStyle.State_Selected:
            p.fillRect(r, QColor(theme.RED_DEEP))
        elif option.state & QStyle.State_MouseOver:
            p.fillRect(r, QColor(255, 255, 255, 10))
        x = r.left() + 12
        w = r.width() - 70
        fm1 = QFontMetrics(self._f1)
        fm2 = QFontMetrics(self._f2)
        p.setFont(self._f1)
        p.setPen(QColor(theme.RED_BRIGHT if current else theme.TEXT))
        p.drawText(QRectF(x, r.top() + 5, w, 20), Qt.AlignLeft | Qt.AlignVCenter,
                   fm1.elidedText(track.title, Qt.ElideRight, w))
        p.setFont(self._f2)
        p.setPen(QColor(theme.DIM))
        p.drawText(QRectF(x, r.top() + 24, w, 16), Qt.AlignLeft | Qt.AlignVCenter,
                   fm2.elidedText(track.display_artist, Qt.ElideRight, w))
        p.drawText(QRectF(r.right() - 56, r.top(), 46, r.height()), Qt.AlignRight | Qt.AlignVCenter,
                   fmt_time(track.duration))
        p.restore()


class QueuePanel(QWidget):
    jump_requested = Signal(int)
    remove_requested = Signal(int)
    clear_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(320)
        self.setObjectName("Sidebar")
        self.setStyleSheet(f"#Sidebar {{ border-left: 1px solid {theme.BORDER}; border-right: none; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 16, 10, 10)
        lay.setSpacing(8)
        head = QHBoxLayout()
        title = QLabel(tr("Queue"))
        title.setObjectName("H2")
        head.addWidget(title)
        head.addStretch(1)
        self.clear_btn = QPushButton(tr("Clear"))
        self.clear_btn.setToolTip(tr("Remove all upcoming songs (the current one keeps playing)"))
        self.clear_btn.setCursor(Qt.PointingHandCursor)
        self.clear_btn.clicked.connect(self.clear_requested)
        head.addWidget(self.clear_btn)
        lay.addLayout(head)
        self.list = QListWidget()
        self.list.setStyleSheet("QListWidget { background: transparent; border: none; }")
        self.list.setItemDelegate(_QueueDelegate(self.list))
        self.list.setMouseTracking(True)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        self.list.itemDoubleClicked.connect(self._jump)
        lay.addWidget(self.list, 1)
        self.info = QLabel("")
        self.info.setObjectName("Dim")
        self.info.setStyleSheet("font-size: 11px;")
        lay.addWidget(self.info)

    def refresh(self, player):
        self.list.setUpdatesEnabled(False)
        self.list.clear()
        if player.current is not None and player.index >= 0:
            header = QListWidgetItem(tr("Now playing"))
            header.setFlags(Qt.NoItemFlags)
            header.setData(Qt.UserRole, None)
            self.list.addItem(header)
            item = QListWidgetItem()
            item.setData(Qt.UserRole, (player.index, player.current, True))
            self.list.addItem(item)
        upcoming = player.upcoming()
        if upcoming:
            header = QListWidgetItem(tr("Next up"))
            header.setFlags(Qt.NoItemFlags)
            header.setData(Qt.UserRole, None)
            self.list.addItem(header)
            for qi, track in upcoming[:1000]:
                item = QListWidgetItem()
                item.setData(Qt.UserRole, (qi, track, False))
                self.list.addItem(item)
        self.list.setUpdatesEnabled(True)
        total = sum(t.duration for _, t in upcoming)
        self.info.setText(tr("{n} upcoming", n=len(upcoming)) + f" · {fmt_time(total)}" if upcoming else
                          tr("Nothing queued. Right-click songs → Add to queue."))
        self.clear_btn.setEnabled(bool(upcoming))

    def _jump(self, item):
        data = item.data(Qt.UserRole)
        if data:
            self.jump_requested.emit(data[0])

    def _menu(self, pos):
        item = self.list.itemAt(pos)
        data = item.data(Qt.UserRole) if item else None
        if not data:
            return
        menu = QMenu(self)
        menu.addAction(tr("Play now"), lambda: self.jump_requested.emit(data[0]))
        if not data[2]:
            menu.addAction(tr("Remove from queue"), lambda: self.remove_requested.emit(data[0]))
        menu.exec(self.list.mapToGlobal(pos))
