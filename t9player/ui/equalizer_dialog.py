"""Equalizer window: a response curve you can shape with the mouse, ten band sliders and presets.

Everything is live - moving a slider is heard right away, nothing has to be confirmed.
"""

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QHBoxLayout, QInputDialog, QLabel,
                               QMessageBox, QPushButton, QSlider, QVBoxLayout, QWidget)

from .. import equalizer as eq, theme
from ..i18n import tr

CUSTOM = "— custom —"          # shown in the preset list once a slider is moved


def _fmt(db):
    return "0" if abs(db) < 0.05 else f"{db:+.0f}"


def _band_label(hz):
    return f"{hz // 1000}k" if hz >= 1000 else str(hz)


class CurveView(QWidget):
    """The response curve. Dragging inside it shapes the nearest band, like a drawing pad."""
    band_dragged = Signal(int, float)       # band index, dB

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(170)
        self.setCursor(Qt.CrossCursor)
        self.setToolTip(tr("Drag inside the graph to shape the sound"))
        self._gains = list(eq.FLAT)
        self._preamp = 0.0
        self._on = False
        self._hover = -1

    def set_values(self, gains, preamp, enabled):
        self._gains, self._preamp, self._on = list(gains), float(preamp), bool(enabled)
        self.update()

    # -- geometry ---------------------------------------------------------------
    def _plot(self):
        return QRectF(self.rect()).adjusted(34, 10, -10, -20)

    def _x_of(self, index):
        r = self._plot()
        return r.left() + r.width() * index / (len(eq.BANDS) - 1)

    def _y_of(self, db):
        r = self._plot()
        return r.center().y() - (db / eq.MAX_DB) * (r.height() / 2)

    def _db_of(self, y):
        r = self._plot()
        return max(-eq.MAX_DB, min(eq.MAX_DB, (r.center().y() - y) / (r.height() / 2) * eq.MAX_DB))

    def _band_at(self, x):
        step = self._plot().width() / (len(eq.BANDS) - 1)
        return max(0, min(len(eq.BANDS) - 1, int(round((x - self._plot().left()) / max(step, 1e-6)))))

    # -- mouse ------------------------------------------------------------------
    def mousePressEvent(self, event):
        self._drag(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self._drag(event)
        else:
            hover = self._band_at(event.position().x())
            if hover != self._hover:
                self._hover = hover
                self.update()

    def leaveEvent(self, event):
        self._hover = -1
        self.update()

    def _drag(self, event):
        index = self._band_at(event.position().x())
        self._hover = index
        self.band_dragged.emit(index, self._db_of(event.position().y()))

    # -- painting ---------------------------------------------------------------
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self._plot()
        p.fillRect(self.rect(), QColor(theme.BG_ALT))
        small = QFont(theme.FONT)
        small.setPixelSize(10)
        p.setFont(small)
        # grid: dB lines and the band frequencies
        for db in (12, 6, 0, -6, -12):
            y = self._y_of(db)
            p.setPen(QPen(QColor(theme.BORDER), 1.6 if db == 0 else 1.0,
                          Qt.SolidLine if db == 0 else Qt.DotLine))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setPen(QColor(theme.FAINT))
            p.drawText(QRectF(0, y - 8, 28, 16), Qt.AlignRight | Qt.AlignVCenter, f"{db:+d}" if db else "0")
        for i, hz in enumerate(eq.BANDS):
            x = self._x_of(i)
            p.setPen(QPen(QColor(theme.BORDER), 1.0, Qt.DotLine))
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            p.setPen(QColor(theme.DIM if i == self._hover else theme.FAINT))
            p.drawText(QRectF(x - 20, r.bottom() + 2, 40, 16), Qt.AlignCenter, _band_label(hz))
        # the curve itself, sampled the same way the filter is built
        colour = QColor(theme.RED_BRIGHT if self._on else theme.FAINT)
        steps = max(2, int(r.width()))
        freqs = [eq.BANDS[0] * (eq.BANDS[-1] / eq.BANDS[0]) ** (i / (steps - 1)) for i in range(steps)]
        curve = eq.response(self._gains, self._preamp, freqs)
        path = QPainterPath()
        for i, db in enumerate(curve):
            point = QPointF(r.left() + r.width() * i / (steps - 1), self._y_of(float(db)))
            path.moveTo(point) if i == 0 else path.lineTo(point)
        under = QPainterPath(path)
        under.lineTo(QPointF(r.right(), self._y_of(0)))
        under.lineTo(QPointF(r.left(), self._y_of(0)))
        under.closeSubpath()
        fill = QLinearGradient(0, r.top(), 0, r.bottom())
        fill.setColorAt(0, QColor(colour.red(), colour.green(), colour.blue(), 70))
        fill.setColorAt(1, QColor(colour.red(), colour.green(), colour.blue(), 10))
        p.fillPath(under, fill)
        p.setPen(QPen(colour, 2.0))
        p.drawPath(path)
        # a dot on every band
        for i, db in enumerate(self._gains):
            p.setPen(Qt.NoPen)
            p.setBrush(colour if i != self._hover else QColor(theme.TEXT))
            size = 4.0 if i != self._hover else 5.5
            p.drawEllipse(QPointF(self._x_of(i), self._y_of(db)), size, size)


class BandSlider(QWidget):
    """One vertical slider with its value above and its frequency below."""
    changed = Signal(float)

    def __init__(self, caption, tooltip, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.value = QLabel("0")
        self.value.setAlignment(Qt.AlignCenter)
        self.value.setStyleSheet(f"color: {theme.DIM}; font-size: 11px;")
        self.slider = QSlider(Qt.Vertical)
        self.slider.setRange(int(-eq.MAX_DB * 2), int(eq.MAX_DB * 2))   # half-dB steps
        self.slider.setPageStep(2)
        self.slider.setToolTip(tooltip)
        self.slider.setCursor(Qt.PointingHandCursor)
        self.slider.valueChanged.connect(lambda v: (self._show(v / 2.0), self.changed.emit(v / 2.0)))
        name = QLabel(caption)
        name.setAlignment(Qt.AlignCenter)
        name.setStyleSheet(f"color: {theme.FAINT}; font-size: 11px;")
        lay.addWidget(self.value)
        lay.addWidget(self.slider, 1, Qt.AlignHCenter)
        lay.addWidget(name)

    def _show(self, db):
        self.value.setText(_fmt(db))
        self.value.setStyleSheet(f"color: {theme.TEXT if abs(db) >= 0.05 else theme.DIM}; font-size: 11px;")

    def set_db(self, db):
        self.slider.blockSignals(True)
        self.slider.setValue(int(round(db * 2)))
        self.slider.blockSignals(False)
        self._show(db)

    def mouseDoubleClickEvent(self, event):
        self.slider.setValue(0)


class EqualizerDialog(QDialog):
    """Changes apply at once; the settings are saved as they are made."""
    changed = Signal()

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle(tr("Equalizer"))
        self.setMinimumWidth(560)
        self._loading = False
        self._gains = eq.clamp(settings["eq_bands"])
        self._preamp = float(settings["eq_preamp"])

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        top = QHBoxLayout()
        self.on = QCheckBox(tr("Equalizer on"))
        self.on.setToolTip(tr("Shape the sound to your taste. While it is on the sound is not bit-perfect."))
        self.on.setChecked(bool(settings["eq_enabled"]))
        self.on.toggled.connect(self._on_toggled)
        self.presets = QComboBox()
        self.presets.setToolTip(tr("Ready-made settings - pick one and adjust it however you like"))
        self.presets.setMinimumWidth(150)
        self.presets.currentIndexChanged.connect(self._on_preset)
        self.save_btn = QPushButton(tr("Save as..."))
        self.save_btn.setToolTip(tr("Remember the current sliders under your own name"))
        self.save_btn.clicked.connect(self._save_preset)
        self.del_btn = QPushButton(tr("Delete"))
        self.del_btn.setToolTip(tr("Remove the selected preset of yours"))
        self.del_btn.clicked.connect(self._delete_preset)
        top.addWidget(self.on)
        top.addStretch(1)
        top.addWidget(QLabel(tr("Preset")))
        top.addWidget(self.presets)
        top.addWidget(self.save_btn)
        top.addWidget(self.del_btn)
        root.addLayout(top)

        self.curve = CurveView()
        self.curve.band_dragged.connect(self._on_dragged)
        root.addWidget(self.curve)

        sliders = QHBoxLayout()
        sliders.setSpacing(2)
        self.preamp = BandSlider(tr("Preamp"), tr("Overall level before the bands - turn it down if boosting clips"))
        self.preamp.changed.connect(self._on_preamp)
        sliders.addWidget(self.preamp)
        line = QWidget()
        line.setFixedWidth(1)
        line.setStyleSheet(f"background: {theme.BORDER};")
        sliders.addWidget(line)
        sliders.addSpacing(6)
        self.bands = []
        for i, hz in enumerate(eq.BANDS):
            s = BandSlider(_band_label(hz), tr("{hz} Hz - double-click to reset this band", hz=hz))
            s.changed.connect(lambda db, index=i: self._on_band(index, db))
            sliders.addWidget(s, 1)
            self.bands.append(s)
        root.addLayout(sliders, 1)

        bottom = QHBoxLayout()
        reset = QPushButton(tr("Reset"))
        reset.setToolTip(tr("Put every slider back to zero"))
        reset.clicked.connect(lambda: self._apply(list(eq.FLAT), 0.0, "Flat"))
        close = QPushButton(tr("Close"))
        close.setToolTip(tr("Close this window - the settings stay"))
        close.clicked.connect(self.accept)
        close.setDefault(True)
        bottom.addWidget(reset)
        bottom.addStretch(1)
        bottom.addWidget(close)
        root.addLayout(bottom)

        self._fill_presets()
        self._show_values()

    # ------------------------------------------------------------------ presets
    def _fill_presets(self):
        self._loading = True
        self.presets.clear()
        self.presets.addItem(tr("Custom"), CUSTOM)
        for name in eq.PRESETS:
            self.presets.addItem(tr(name), name)
        custom = self.settings["eq_custom"]
        if custom:
            self.presets.insertSeparator(self.presets.count())
            for name in sorted(custom):
                self.presets.addItem(name, name)
        self._loading = False
        self._select_preset(self.settings["eq_preset"])

    def _select_preset(self, name):
        self._loading = True
        index = self.presets.findData(name)
        self.presets.setCurrentIndex(index if index >= 0 else 0)
        self._loading = False
        self.del_btn.setEnabled(name in self.settings["eq_custom"])

    def _on_preset(self, _index):
        if self._loading:
            return
        name = self.presets.currentData()
        if name == CUSTOM:
            return
        custom = self.settings["eq_custom"].get(name)
        if custom:
            self._apply(eq.clamp(custom.get("bands")), float(custom.get("preamp", 0.0) or 0.0), name)
        elif name in eq.PRESETS:
            self._apply(list(eq.PRESETS[name]), self._preamp, name)

    def _save_preset(self):
        name, ok = QInputDialog.getText(self, tr("Save preset"), tr("Name:"))
        name = (name or "").strip()
        if not ok or not name:
            return
        if name in eq.PRESETS:
            QMessageBox.information(self, tr("Save preset"),
                                    tr("“{name}” is one of the ready-made presets - pick another name.",
                                       name=name))
            return
        custom = dict(self.settings["eq_custom"])
        custom[name] = {"preamp": self._preamp, "bands": list(self._gains)}
        self.settings.set("eq_custom", custom)
        self.settings.set("eq_preset", name)
        self._fill_presets()

    def _delete_preset(self):
        name = self.presets.currentData()
        custom = dict(self.settings["eq_custom"])
        if name not in custom:
            return
        del custom[name]
        self.settings.set("eq_custom", custom)
        self.settings.set("eq_preset", CUSTOM)
        self._fill_presets()

    # ------------------------------------------------------------------ values
    def _on_toggled(self, on):
        self.settings.set("eq_enabled", bool(on))
        self.curve.set_values(self._gains, self._preamp, on)
        self.changed.emit()

    def _on_band(self, index, db):
        self._gains[index] = db
        self._store(CUSTOM)

    def _on_preamp(self, db):
        self._preamp = db
        self._store(CUSTOM)

    def _on_dragged(self, index, db):
        self.bands[index].set_db(db)
        self._gains[index] = db
        self._store(CUSTOM)

    def _apply(self, gains, preamp, preset):
        self._gains, self._preamp = eq.clamp(gains), float(preamp)
        self._show_values()
        self._store(preset)

    def _show_values(self):
        for slider, db in zip(self.bands, self._gains):
            slider.set_db(db)
        self.preamp.set_db(self._preamp)
        self.curve.set_values(self._gains, self._preamp, self.on.isChecked())

    def _store(self, preset):
        if self._loading:
            return
        self.settings.update({"eq_bands": list(self._gains), "eq_preamp": self._preamp, "eq_preset": preset})
        if preset != CUSTOM:
            self._select_preset(preset)
        else:
            self._loading = True
            self.presets.setCurrentIndex(0)
            self._loading = False
            self.del_btn.setEnabled(False)
        self.curve.set_values(self._gains, self._preamp, self.on.isChecked())
        if not self.on.isChecked() and not eq.is_flat(self._gains, self._preamp):
            self.on.setChecked(True)            # touching a slider turns it on, nobody likes a dead control
            return
        self.changed.emit()
