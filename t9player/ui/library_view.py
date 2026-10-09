"""Track list: fast model (own sorting/filtering in Python lists) + painted delegate."""

from PySide6.QtCore import (QAbstractTableModel, QByteArray, QMimeData, QModelIndex, QPoint, QRectF,
                            QSize, Qt, QTimer, Signal)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QPushButton, QStyle, QStyledItemDelegate, QTableView,
                               QVBoxLayout, QWidget)

from .. import icons, theme
from ..i18n import songs as n_songs, times as n_times, tr
from .widgets import fmt_time, paint_placeholder

COLUMNS = ("#", "Title", "Album", "Year", "Plays", "Format", "Time")
COL_NUM, COL_TITLE, COL_ALBUM, COL_YEAR, COL_PLAYS, COL_FORMAT, COL_TIME = range(7)
PLAYS_WIDTH = 80
ROW_HEIGHT = 54
COMPACT_HEIGHT = 34
SORT_ARTIST, SORT_ADDED = 100, 101       # sort keys without their own column
MIME_ROWS = "application/x-t9-rows"


def _natural_key(text):
    return (text or "").casefold()


SORT_KEYS = {
    COL_NUM: None,   # list order
    COL_TITLE: lambda t: (_natural_key(t.title), _natural_key(t.display_artist)),
    COL_ALBUM: lambda t: (_natural_key(t.album), t.disc, t.track, _natural_key(t.title)),
    COL_YEAR: lambda t: (t.year or "9999", _natural_key(t.album), t.disc, t.track),
    COL_PLAYS: lambda t: (t.plays, t.last_played),
    COL_FORMAT: lambda t: (-(t.bits or 0), -(t.samplerate or 0), t.codec, -(t.bitrate or 0)),
    COL_TIME: lambda t: t.duration,
    SORT_ARTIST: lambda t: (_natural_key(t.display_artist), _natural_key(t.album), t.disc, t.track),
    SORT_ADDED: lambda t: -(t.added or 0),
}

# the "Sort by" menu: key, label, column, descending
SORT_OPTIONS = (
    ("custom", "Custom order", COL_NUM, False),
    ("title", "Title", COL_TITLE, False),
    ("artist", "Artist", SORT_ARTIST, False),
    ("album", "Album", COL_ALBUM, False),
    ("added", "Recently added", SORT_ADDED, False),
    ("year", "Release date", COL_YEAR, True),
    ("time", "Duration", COL_TIME, False),
)


class TrackModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._source = []          # list order as given (playlist order etc.)
        self._rows = []            # (list_position, track) after filter + sort
        self._filter = ""
        self._sort_col = COL_NUM
        self._sort_order = Qt.AscendingOrder
        self.playing_path = None
        self._row_of_path = {}
        self.reorderable = False

    # -- data management ------------------------------------------------------------
    def set_tracks(self, tracks):
        self._source = list(tracks)
        self._rebuild()

    def tracks(self):
        return [t for _, t in self._rows]

    def source_tracks(self):
        return list(self._source)

    def set_filter(self, text):
        text = (text or "").strip().casefold()
        if text != self._filter:
            self._filter = text
            self._rebuild()

    def sort(self, column, order=Qt.AscendingOrder):
        self._sort_col = column
        self._sort_order = order
        self._rebuild()

    def sort_state(self):
        return self._sort_col, self._sort_order

    def _rebuild(self):
        self.beginResetModel()
        rows = list(enumerate(self._source))
        if self._filter:
            terms = self._filter.split()
            rows = [(i, t) for i, t in rows if all(term in t.search_text for term in terms)]
        key = SORT_KEYS.get(self._sort_col)
        reverse = self._sort_order == Qt.DescendingOrder
        if key is None:
            if reverse:
                rows.reverse()
        else:
            rows.sort(key=lambda it: key(it[1]), reverse=reverse)
        self._rows = rows
        self._row_of_path = {t.path: r for r, (_, t) in enumerate(rows)}
        self.endResetModel()

    def track_at(self, row):
        if 0 <= row < len(self._rows):
            return self._rows[row][1]
        return None

    def list_position(self, row):
        if 0 <= row < len(self._rows):
            return self._rows[row][0]
        return -1

    def row_of(self, path):
        return self._row_of_path.get(path, -1)

    def set_playing(self, path):
        old = self.row_of(self.playing_path) if self.playing_path else -1
        self.playing_path = path
        new = self.row_of(path) if path else -1
        for r in (old, new):
            if r >= 0:
                self.dataChanged.emit(self.index(r, 0), self.index(r, len(COLUMNS) - 1))

    def refresh_path(self, path):
        r = self.row_of(path)
        if r >= 0:
            self.dataChanged.emit(self.index(r, 0), self.index(r, len(COLUMNS) - 1))

    def total_duration(self):
        return sum(t.duration for _, t in self._rows)

    # -- Qt model API ---------------------------------------------------------------
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal:
            if role == Qt.DisplayRole:
                return tr(COLUMNS[section]) if section != COL_TIME else ""
            if role == Qt.DecorationRole and section == COL_TIME:
                return icons.icon("clock", theme.DIM, 14)
            if role == Qt.TextAlignmentRole:
                return int(Qt.AlignRight | Qt.AlignVCenter) if section in (COL_TIME, COL_PLAYS) else int(Qt.AlignLeft | Qt.AlignVCenter)
            if role == Qt.ToolTipRole and section == COL_PLAYS:
                return tr("How many times you listened to the song (counted after half of it, or 30 s)")
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        t = self._rows[index.row()][1]
        col = index.column()
        if role == Qt.DisplayRole:
            if col == COL_NUM:
                return str(index.row() + 1)
            if col == COL_TITLE:
                return t.title
            if col == COL_ALBUM:
                return t.album
            if col == COL_YEAR:
                return t.year
            if col == COL_FORMAT:
                return t.format_label
            if col == COL_PLAYS:
                return str(t.plays)
            if col == COL_TIME:
                return fmt_time(t.duration)
        elif role == Qt.ToolTipRole:
            if col == COL_TITLE:
                return f"{t.title}\n{t.display_artist}"
            if col == COL_FORMAT:
                return _format_tooltip(t)
            if col == COL_ALBUM and t.album:
                return t.album
            if col == COL_PLAYS:
                return n_times(t.plays)
        elif role == Qt.UserRole:
            return t
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemIsDropEnabled if self.reorderable else Qt.NoItemFlags
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if self.reorderable:
            flags |= Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled
        return flags

    # -- drag & drop inside a playlist (the window does the actual reordering) ----
    rows_dropped = Signal(list, int)

    def supportedDropActions(self):
        return Qt.MoveAction

    def mimeTypes(self):
        return [MIME_ROWS]

    def mimeData(self, indexes):
        rows = sorted({i.row() for i in indexes})
        data = QMimeData()
        data.setData(MIME_ROWS, QByteArray(",".join(map(str, rows)).encode("ascii")))
        return data

    def dropMimeData(self, data, action, row, column, parent):
        if not self.reorderable or not data.hasFormat(MIME_ROWS):
            return False
        try:
            rows = [int(x) for x in bytes(data.data(MIME_ROWS)).decode("ascii").split(",") if x]
        except ValueError:
            return False
        if row < 0:
            row = parent.row() if parent.isValid() else self.rowCount()
        self.rows_dropped.emit(rows, row)
        return False          # the list is rebuilt from the playlist, nothing to remove here


def _format_tooltip(t):
    parts = [t.codec or "?"]
    if t.samplerate:
        parts.append(f"{t.samplerate / 1000:g} kHz")
    if t.bits:
        parts.append(f"{t.bits}-bit")
    if t.channels:
        parts.append({1: "mono", 2: "stereo"}.get(t.channels, f"{t.channels} channels"))
    if t.bitrate:
        parts.append(f"{t.bitrate // 1000} kbps")
    text = " \u00b7 ".join(parts)
    if t.hires:
        text += "\n" + tr("Hi-Res audio")
    return text


class TrackDelegate(QStyledItemDelegate):
    def __init__(self, view, covers):
        super().__init__(view)
        self.view = view
        self.covers = covers
        self._title_font = QFont(theme.FONT)
        self._title_font.setPixelSize(14)
        self._title_font.setWeight(QFont.DemiBold)
        self._sub_font = QFont(theme.FONT)
        self._sub_font.setPixelSize(12)
        self._cell_font = QFont(theme.FONT)
        self._cell_font.setPixelSize(13)
        self._badge_font = QFont(theme.FONT)
        self._badge_font.setPixelSize(9)
        self._badge_font.setWeight(QFont.Bold)

    def sizeHint(self, option, index):
        return QSize(100, COMPACT_HEIGHT if self.view.compact else ROW_HEIGHT)

    def paint(self, p, option, index):
        model = index.model()
        t = model.track_at(index.row())
        if t is None:
            return
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = option.rect
        selected = bool(option.state & QStyle.State_Selected)
        hovered = index.row() == self.view.hover_row
        playing = model.playing_path == t.path
        if selected:
            p.fillRect(r, QColor(theme.RED_DEEP))
        elif hovered:
            p.fillRect(r, QColor(255, 255, 255, 10))
        col = index.column()
        text_color = QColor(theme.RED_BRIGHT) if playing else QColor(theme.TEXT)
        dim = QColor(theme.DIM)
        if col == COL_NUM:
            rect = QRectF(r).adjusted(4, 0, -4, 0)
            btn = QRectF(rect.right() - 22, rect.center().y() - 10, 20, 20)
            sounding = playing and self.view.is_playing()
            if hovered:
                # one click on this button plays the song, the next click pauses it
                hot = self.view.hover_button
                if hot:
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(theme.RED))
                    p.drawEllipse(btn.adjusted(-3, -3, 3, 3))
                name = "pause" if sounding else "play"
                pm = icons.pixmap(name, theme.ON_ACCENT if hot else (theme.RED_BRIGHT if playing else theme.TEXT), 16)
                p.drawPixmap(btn.adjusted(2, 2, -2, -2), pm, QRectF(pm.rect()))
            elif playing:
                pm = icons.pixmap("volume" if sounding else "pause", theme.RED_BRIGHT, 16)
                p.drawPixmap(btn.adjusted(2, 2, -2, -2), pm, QRectF(pm.rect()))
            else:
                p.setFont(self._cell_font)
                p.setPen(dim)
                p.drawText(rect, Qt.AlignRight | Qt.AlignVCenter, index.data())
        elif col == COL_TITLE and self.view.compact:
            x = r.left() + 6
            width = r.right() - x - 8
            heart_w = 18 if t.favorite else 0
            if t.favorite:
                hp = icons.pixmap("heart", theme.RED, 12)
                p.drawPixmap(QRectF(r.right() - 20, r.center().y() - 6, 12, 12), hp, QRectF(hp.rect()))
            fm = QFontMetrics(self._title_font)
            title = fm.elidedText(t.title, Qt.ElideRight, int(width - heart_w))
            p.setFont(self._title_font)
            p.setPen(text_color)
            p.drawText(QRectF(x, r.top(), width, r.height()), Qt.AlignLeft | Qt.AlignVCenter, title)
            rest = width - heart_w - fm.horizontalAdvance(title) - 10
            if rest > 30:
                p.setFont(self._sub_font)
                p.setPen(dim)
                fm2 = QFontMetrics(self._sub_font)
                p.drawText(QRectF(x + fm.horizontalAdvance(title) + 10, r.top(), rest, r.height()),
                           Qt.AlignLeft | Qt.AlignVCenter, fm2.elidedText(t.display_artist, Qt.ElideRight, int(rest)))
        elif col == COL_TITLE:
            thumb = QRectF(r.left() + 6, r.top() + (r.height() - 40) / 2, 40, 40)
            path = QPainterPath()
            path.addRoundedRect(thumb, 5, 5)
            pm = self.covers.thumb(t)
            if pm:
                p.save()
                p.setClipPath(path)
                p.setRenderHint(QPainter.SmoothPixmapTransform)
                p.drawPixmap(thumb, pm, QRectF(pm.rect()))
                p.restore()
            elif pm is False:
                paint_placeholder(p, thumb, 5)
            else:
                p.fillPath(path, QColor("#1c1c21"))
            x = thumb.right() + 12
            width = r.right() - x - 8
            heart_w = 0
            if t.favorite:
                heart_w = 18
                hp = icons.pixmap("heart", theme.RED, 13)
                p.drawPixmap(QRectF(r.right() - 20, r.center().y() - 6.5, 13, 13), hp, QRectF(hp.rect()))
            p.setFont(self._title_font)
            fm = QFontMetrics(self._title_font)
            p.setPen(text_color)
            p.drawText(QRectF(x, r.top() + 8, width - heart_w, 20), Qt.AlignLeft | Qt.AlignVCenter,
                       fm.elidedText(t.title, Qt.ElideRight, int(width - heart_w)))
            p.setFont(self._sub_font)
            fm2 = QFontMetrics(self._sub_font)
            p.setPen(dim)
            p.drawText(QRectF(x, r.top() + 28, width - heart_w, 18), Qt.AlignLeft | Qt.AlignVCenter,
                       fm2.elidedText(t.display_artist, Qt.ElideRight, int(width - heart_w)))
        elif col == COL_FORMAT:
            p.setFont(self._cell_font)
            rect = QRectF(r).adjusted(6, 0, -6, 0)
            label = t.format_label
            fm = QFontMetrics(self._cell_font)
            p.setPen(dim)
            p.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter, fm.elidedText(label, Qt.ElideRight, int(rect.width())))
            if t.hires:
                lw = fm.horizontalAdvance(label) + 8
                if lw + 44 < rect.width():
                    badge = QRectF(rect.left() + lw, rect.center().y() - 7, 40, 14)
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(theme.RED_DEEP))
                    p.drawRoundedRect(badge, 3, 3)
                    p.setFont(self._badge_font)
                    p.setPen(QColor(theme.RED_BRIGHT))
                    p.drawText(badge, Qt.AlignCenter, "HI-RES")
        elif col == COL_PLAYS:
            rect = QRectF(r).adjusted(6, 0, -12, 0)
            p.setFont(self._title_font)
            p.setPen(QColor(theme.RED_BRIGHT) if t.plays else dim)
            p.drawText(rect, Qt.AlignRight | Qt.AlignVCenter, f"{t.plays}×")
        else:
            p.setFont(self._cell_font)
            p.setPen(dim if col != COL_ALBUM or not playing else text_color)
            align = Qt.AlignRight | Qt.AlignVCenter if col == COL_TIME else Qt.AlignLeft | Qt.AlignVCenter
            rect = QRectF(r).adjusted(6, 0, -10 if col == COL_TIME else -6, 0)
            fm = QFontMetrics(self._cell_font)
            p.drawText(rect, align, fm.elidedText(index.data() or "", Qt.ElideRight, int(rect.width())))
        p.restore()


class TrackTable(QTableView):
    activated_row = Signal(int)
    play_clicked = Signal(int)          # the round play/pause button in the # column
    context_requested = Signal(QPoint)

    def __init__(self, covers, is_playing_fn, parent=None, embedded=False):
        super().__init__(parent)
        self.hover_row = -1
        self.hover_button = False
        self.embedded = embedded
        self.compact = False
        self._drop_row = None           # where a dragged song would land (drawn as a line)
        self.is_playing = is_playing_fn
        self.model_ = TrackModel(self)
        self.setModel(self.model_)
        self.setItemDelegate(TrackDelegate(self, covers))
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setMouseTracking(True)
        self.setSortingEnabled(True)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(24)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.context_requested)
        self.setDragEnabled(False)
        vh = self.verticalHeader()
        vh.setVisible(False)
        vh.setSectionResizeMode(QHeaderView.Fixed)
        vh.setDefaultSectionSize(ROW_HEIGHT)
        hh = self.horizontalHeader()
        hh.setHighlightSections(False)
        hh.setSectionsMovable(False)
        hh.setStretchLastSection(False)
        hh.setSectionResizeMode(COL_NUM, QHeaderView.Fixed)
        hh.setSectionResizeMode(COL_TITLE, QHeaderView.Fixed)
        hh.setSectionResizeMode(COL_ALBUM, QHeaderView.Fixed)
        hh.setSectionResizeMode(COL_YEAR, QHeaderView.Fixed)
        hh.setSectionResizeMode(COL_PLAYS, QHeaderView.Fixed)
        hh.setSectionResizeMode(COL_FORMAT, QHeaderView.Fixed)
        hh.setSectionResizeMode(COL_TIME, QHeaderView.Fixed)
        hh.resizeSection(COL_NUM, 48)
        hh.resizeSection(COL_ALBUM, 260)
        hh.resizeSection(COL_YEAR, 64)
        hh.resizeSection(COL_PLAYS, PLAYS_WIDTH)
        self.setColumnHidden(COL_PLAYS, True)
        hh.resizeSection(COL_FORMAT, 150)
        hh.resizeSection(COL_TIME, 70)
        hh.setSortIndicatorShown(True)
        hh.setSortIndicator(COL_NUM, Qt.AscendingOrder)
        self.doubleClicked.connect(self._on_double_click)
        if embedded:
            self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.model_.modelReset.connect(self.fit_height)
        self._viewport_timer = QTimer(self)
        self._viewport_timer.setSingleShot(True)
        self._viewport_timer.setInterval(40)
        self._viewport_timer.timeout.connect(self.viewport().update)
        covers.thumb_ready.connect(self._on_thumb)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_columns()

    def fit_height(self):
        """Embedded tables show every row; the page around them scrolls."""
        if self.embedded:
            rows = self.model_.rowCount()
            row_h = COMPACT_HEIGHT if self.compact else ROW_HEIGHT
            self.setFixedHeight(self.horizontalHeader().height() + rows * row_h + 4)

    def wheelEvent(self, event):
        if self.embedded:
            event.ignore()          # let the page scroll
            return
        super().wheelEvent(event)

    def _fit_columns(self):
        """Title gets ~60 % of the flexible width, album the rest; small columns stay fixed."""
        hh = self.horizontalHeader()
        width = self.viewport().width()
        fmt = 150 if width > 760 else 110
        hh.resizeSection(COL_FORMAT, fmt)
        hh.resizeSection(COL_YEAR, 64 if width > 640 else 0)
        hh.resizeSection(COL_PLAYS, PLAYS_WIDTH)
        fixed = sum(hh.sectionSize(c) for c in (COL_NUM, COL_YEAR, COL_PLAYS, COL_FORMAT, COL_TIME)
                    if not hh.isSectionHidden(c))
        flexible = max(200, width - fixed)
        if hh.isSectionHidden(COL_ALBUM):
            hh.resizeSection(COL_TITLE, flexible)
            return
        title = int(flexible * 0.6)
        hh.resizeSection(COL_TITLE, title)
        hh.resizeSection(COL_ALBUM, flexible - title)

    def set_compact(self, compact):
        self.compact = bool(compact)
        self.verticalHeader().setDefaultSectionSize(COMPACT_HEIGHT if self.compact else ROW_HEIGHT)
        self.fit_height()
        self.viewport().update()

    def set_reorderable(self, on):
        """Drag & drop of songs inside a playlist (custom order only)."""
        self.model_.reorderable = bool(on)
        self.setDragEnabled(on)
        self.setAcceptDrops(on)
        self.viewport().setAcceptDrops(on)
        self.setDropIndicatorShown(False)      # we draw our own insertion line
        self.setDragDropMode(QAbstractItemView.InternalMove if on else QAbstractItemView.NoDragDrop)
        self.setDefaultDropAction(Qt.MoveAction)

    # -- drag & drop: show a line between the songs where the drop goes -------------
    def _insert_row(self, y):
        row = self.rowAt(int(y))
        if row < 0:
            return self.model_.rowCount()
        rect = self.visualRect(self.model_.index(row, 0))
        return row + 1 if y > rect.center().y() else row

    def dragEnterEvent(self, event):
        if self.model_.reorderable and event.mimeData().hasFormat(MIME_ROWS):
            event.setDropAction(Qt.MoveAction)
            event.accept()
            return
        event.ignore()

    def dragMoveEvent(self, event):
        if not (self.model_.reorderable and event.mimeData().hasFormat(MIME_ROWS)):
            event.ignore()
            return
        super().dragMoveEvent(event)           # keeps the auto-scroll near the edges
        row = self._insert_row(event.position().y())
        if row != self._drop_row:
            self._drop_row = row
            self.viewport().update()
        event.setDropAction(Qt.MoveAction)
        event.accept()

    def dragLeaveEvent(self, event):
        self._drop_row = None
        self.viewport().update()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        row = self._drop_row if self._drop_row is not None else self._insert_row(event.position().y())
        self._drop_row = None
        self.viewport().update()
        data = event.mimeData()
        if not (self.model_.reorderable and data.hasFormat(MIME_ROWS)):
            event.ignore()
            return
        try:
            rows = [int(x) for x in bytes(data.data(MIME_ROWS)).decode("ascii").split(",") if x]
        except ValueError:
            rows = []
        event.setDropAction(Qt.MoveAction)
        event.accept()
        if rows:
            self.model_.rows_dropped.emit(rows, row)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._drop_row is None:
            return
        n = self.model_.rowCount()
        if n == 0:
            y = 2
        elif self._drop_row >= n:
            y = self.visualRect(self.model_.index(n - 1, 0)).bottom() + 1
        else:
            y = self.visualRect(self.model_.index(self._drop_row, 0)).top()
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.Antialiasing)
        color = QColor(theme.RED_BRIGHT)
        p.setPen(QPen(color, 2))
        p.drawLine(QPoint(14, y), QPoint(self.viewport().width() - 8, y))
        p.setBrush(QColor(theme.BG))
        p.drawEllipse(QRectF(6, y - 4, 8, 8))

    def set_visible_columns(self, columns):
        for c in range(len(COLUMNS)):
            self.setColumnHidden(c, c not in columns)
        self._fit_columns()

    def _on_button(self, pos):
        idx = self.indexAt(pos)
        return idx.isValid() and idx.column() == COL_NUM

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._on_button(event.position().toPoint()):
            row = self.indexAt(event.position().toPoint()).row()
            self.selectRow(row)
            self.play_clicked.emit(row)
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton and self._on_button(event.position().toPoint()):
            # a quick second click on the button is just another click (pause again)
            self.play_clicked.emit(self.indexAt(event.position().toPoint()).row())
            return
        super().mouseDoubleClickEvent(event)

    def _on_double_click(self, idx):
        if idx.column() != COL_NUM:
            self.activated_row.emit(idx.row())

    def _on_thumb(self, path):
        if not self._viewport_timer.isActive():
            self._viewport_timer.start()

    def mouseMoveEvent(self, event):
        row = self.rowAt(int(event.position().y()))
        on_button = self._on_button(event.position().toPoint())
        if on_button != self.hover_button:
            self.hover_button = on_button
            self.setCursor(Qt.PointingHandCursor if on_button else Qt.ArrowCursor)
            if row >= 0:
                self.viewport().update(self.visualRect(self.model_.index(row, COL_NUM)))
        if row != self.hover_row:
            old = self.hover_row
            self.hover_row = row
            for r in (old, row):
                if r >= 0:
                    self.viewport().update(self.visualRect(self.model_.index(r, 0)).united(
                        self.visualRect(self.model_.index(r, len(COLUMNS) - 1))))
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        old = self.hover_row
        self.hover_row = -1
        self.hover_button = False
        if old >= 0:
            self.viewport().update()
        super().leaveEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            idx = self.currentIndex()
            if idx.isValid():
                self.activated_row.emit(idx.row())
                return
        super().keyPressEvent(event)

    def selected_tracks(self):
        rows = sorted({i.row() for i in self.selectionModel().selectedRows()})
        return [self.model_.track_at(r) for r in rows if self.model_.track_at(r) is not None]

    def selected_rows(self):
        return sorted({i.row() for i in self.selectionModel().selectedRows()})


class SortButton(QPushButton):
    """'Custom order  ☰' - text and the list icon centred on the same line."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFlat(True)
        self._hover = False
        self.setFixedHeight(32)

    def setText(self, text):
        super().setText(text)
        fm = QFontMetrics(self._font())
        self.setFixedWidth(fm.horizontalAdvance(text) + 16 + 8 + 16)
        self.update()

    def _font(self):
        f = QFont(theme.FONT)
        f.setPixelSize(13)
        return f

    def enterEvent(self, event):
        self._hover = True
        self.update()

    def leaveEvent(self, event):
        self._hover = False
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        color = theme.TEXT if self._hover or self.isDown() else theme.DIM
        f = self._font()
        p.setFont(f)
        p.setPen(QColor(color))
        fm = QFontMetrics(f)
        text_w = fm.horizontalAdvance(self.text())
        x = 8
        p.drawText(QRectF(x, 0, text_w + 2, self.height()), Qt.AlignLeft | Qt.AlignVCenter, self.text())
        pm = icons.pixmap("list", color, 16)
        p.drawPixmap(QRectF(x + text_w + 8, (self.height() - 16) / 2, 16, 16), pm, QRectF(pm.rect()))


class LibraryPage(QWidget):
    """Header (title, stats, search, sort, play buttons) + track table."""
    play_requested = Signal(list, int)        # tracks in display order, start row
    shuffle_requested = Signal(list)
    sort_chosen = Signal(object, str)         # view key, sort option key
    density_chosen = Signal(str)              # "list" | "compact"
    reorder_requested = Signal(object, list, int)   # view key, rows, drop row

    def __init__(self, covers, is_playing_fn, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 22, 20, 0)
        lay.setSpacing(12)
        head = QHBoxLayout()
        head.setSpacing(12)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.title = QLabel(tr("Songs"))
        self.title.setObjectName("H1")
        self.stats = QLabel("")
        self.stats.setObjectName("Dim")
        titles.addWidget(self.title)
        titles.addWidget(self.stats)
        head.addLayout(titles, 1)
        self.play_btn = QPushButton("  " + tr("Play"))
        self.play_btn.setObjectName("Primary")
        self.play_btn.setIcon(icons.icon("play", theme.ON_ACCENT, 16))
        self.play_btn.setToolTip(tr("Play this list from the top"))
        self.play_btn.setCursor(Qt.PointingHandCursor)
        self.shuffle_btn = QPushButton("  " + tr("Shuffle"))
        self.shuffle_btn.setIcon(icons.icon("shuffle", theme.TEXT, 16))
        self.shuffle_btn.setToolTip(tr("Play this list in random order"))
        self.shuffle_btn.setCursor(Qt.PointingHandCursor)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Search title, artist, album...  (Ctrl+F)"))
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(280)
        self.search.addAction(icons.icon("search", theme.DIM, 16), QLineEdit.LeadingPosition)
        self.search.setToolTip(tr("Type to filter the list instantly"))
        self.sort_btn = SortButton()
        self.sort_btn.setText(tr("Custom order"))
        self.sort_btn.setToolTip(tr("Sort the list and choose the layout"))
        self.sort_btn.clicked.connect(self._sort_menu)
        head.addWidget(self.search, 0, Qt.AlignVCenter)
        head.addWidget(self.sort_btn, 0, Qt.AlignVCenter)
        head.addWidget(self.shuffle_btn, 0, Qt.AlignVCenter)
        head.addWidget(self.play_btn, 0, Qt.AlignVCenter)
        lay.addLayout(head)
        self.table = TrackTable(covers, is_playing_fn, self)
        lay.addWidget(self.table, 1)
        self.empty = QLabel("", self)
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setObjectName("Dim")
        self.empty.setWordWrap(True)
        self.empty.hide()
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(140)
        self._search_timer.timeout.connect(self._apply_search)
        self.search.textChanged.connect(lambda _: self._search_timer.start())
        self.table.activated_row.connect(self._on_activated)
        self.play_btn.clicked.connect(lambda: self._emit_play(0))
        self.shuffle_btn.clicked.connect(lambda: self.shuffle_requested.emit(self.table.model_.tracks()))
        self.table.model_.modelReset.connect(self._update_stats)
        self.table.model_.modelReset.connect(self._update_sort_label)
        self.table.model_.rows_dropped.connect(lambda rows, row: self.reorder_requested.emit(self.view_key, rows, row))
        self.view_key = None
        self._empty_text = ""

    def set_content(self, key, title, tracks, sort=None, empty_text="", show_plays=False):
        model = self.table.model_
        if self.table.isColumnHidden(COL_PLAYS) == show_plays:
            self.table.setColumnHidden(COL_PLAYS, not show_plays)
            self.table._fit_columns()
        same_view = key == self.view_key
        scroll = self.table.verticalScrollBar().value() if same_view else 0
        self.view_key = key
        self.title.setText(title)
        self._empty_text = empty_text
        if not same_view:
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
            model._filter = ""
            if sort is not None:
                model._sort_col, model._sort_order = sort
            self._sync_header()
        model.set_tracks(tracks)
        self._update_reorder()
        if same_view:
            QTimer.singleShot(0, lambda: self.table.verticalScrollBar().setValue(scroll))
        else:
            self.table.scrollToTop()

    def _sync_header(self):
        model = self.table.model_
        hh = self.table.horizontalHeader()
        hh.blockSignals(True)
        if model._sort_col < len(COLUMNS):
            hh.setSortIndicatorShown(True)
            hh.setSortIndicator(model._sort_col, model._sort_order)
        else:
            hh.setSortIndicatorShown(False)
        hh.blockSignals(False)

    def current_sort_key(self):
        col, order = self.table.model_.sort_state()
        for key, _, c, desc in SORT_OPTIONS:
            if c == col and (desc == (order == Qt.DescendingOrder) or c == COL_NUM):
                return key
        return None

    def apply_sort_key(self, key):
        for k, _, col, desc in SORT_OPTIONS:
            if k == key:
                self.table.model_.sort(col, Qt.DescendingOrder if desc else Qt.AscendingOrder)
                self._sync_header()
                self._update_reorder()
                return

    def _update_reorder(self):
        is_playlist = bool(self.view_key) and self.view_key[0] == "playlist"
        self.table.set_reorderable(is_playlist and self.table.model_.sort_state()[0] == COL_NUM
                                   and not self.table.model_._filter)

    def _update_sort_label(self):
        key = self.current_sort_key()
        label = next((lab for k, lab, _, _ in SORT_OPTIONS if k == key), None)
        self.sort_btn.setText(tr(label) if label else tr("Sorted"))

    def _sort_menu(self):
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        head = menu.addAction(tr("Sort by"))
        head.setEnabled(False)
        current = self.current_sort_key()
        for key, label, _, _ in SORT_OPTIONS:
            act = menu.addAction(tr(label), lambda k=key: self._choose_sort(k))
            act.setCheckable(True)
            act.setChecked(key == current)
        menu.addSeparator()
        head2 = menu.addAction(tr("Layout"))
        head2.setEnabled(False)
        for key, label, icon_name in (("compact", "Compact", "list"), ("list", "List", "songs")):
            act = menu.addAction(icons.icon(icon_name, theme.TEXT, 16), tr(label),
                                 lambda k=key: self.density_chosen.emit(k))
            act.setCheckable(True)
            act.setChecked(self.table.compact == (key == "compact"))
        menu.exec(self.sort_btn.mapToGlobal(QPoint(0, self.sort_btn.height())))

    def _choose_sort(self, key):
        self.apply_sort_key(key)
        self.sort_chosen.emit(self.view_key, key)

    def _apply_search(self):
        self.table.model_.set_filter(self.search.text())
        self._update_reorder()

    def _emit_play(self, row):
        tracks = self.table.model_.tracks()
        if tracks:
            self.play_requested.emit(tracks, row)

    def _on_activated(self, row):
        self._emit_play(row)

    def _update_stats(self):
        model = self.table.model_
        n = model.rowCount()
        total = model.total_duration()
        hours = total / 3600
        dur = f"{hours:.1f} h" if hours >= 1 else fmt_time(total)
        self.stats.setText(f"{n_songs(n)} \u00b7 {dur}" if n else "")
        empty = n == 0
        self.empty.setVisible(empty)
        if empty:
            self.empty.setText(tr("No results for this search") if model._filter else self._empty_text)
            self.empty.setGeometry(self.table.geometry().adjusted(20, 60, -20, -20))
            self.empty.raise_()
        self.play_btn.setEnabled(not empty)
        self.shuffle_btn.setEnabled(not empty)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.empty.isVisible():
            self.empty.setGeometry(self.table.geometry().adjusted(20, 60, -20, -20))
