"""Small custom-painted widgets shared by the main window and the mini player."""

import os

from PySide6.QtCore import (QEasingCurve, QPointF, QRectF, QSize, Qt, QTimer,
                            QVariantAnimation, Signal)
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QImage, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap, QRadialGradient)
from PySide6.QtWidgets import QAbstractButton, QHBoxLayout, QLabel, QSizePolicy, QWidget

from .. import icons, paths, theme
from ..i18n import tr


def fmt_time(seconds):
    seconds = max(0, int(seconds or 0))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class IconButton(QAbstractButton):
    """Flat vector icon button. `filled=True` draws the round red play button."""

    def __init__(self, icon_name, tooltip="", size=36, icon_size=20, filled=False,
                 checkable=False, parent=None):
        super().__init__(parent)
        self._icon = icon_name
        self._size = size
        self._icon_size = icon_size
        self._filled = filled
        self._hover = False
        self._color = theme.DIM
        self._active_color = theme.RED_BRIGHT
        self.setCheckable(checkable)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(size, size)
        self.setFocusPolicy(Qt.NoFocus)
        if tooltip:
            self.setToolTip(tooltip)

    def set_icon(self, name):
        if name != self._icon:
            self._icon = name
            self.update()

    def set_colors(self, normal=None, active=None):
        if normal:
            self._color = normal
        if active:
            self._active_color = active
        self.update()

    def sizeHint(self):
        return QSize(self._size, self._size)

    def enterEvent(self, event):
        self._hover = True
        self.update()

    def leaveEvent(self, event):
        self._hover = False
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = self.rect()
        if self._filled:
            c = QColor(theme.RED_BRIGHT if self._hover else theme.RED)
            if self.isDown():
                c = QColor(theme.RED_DARK)
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            p.drawEllipse(QRectF(r).adjusted(1, 1, -1, -1))
            color = theme.ON_ACCENT
        else:
            if self._hover:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(255, 255, 255, 14))
                p.drawEllipse(QRectF(r).adjusted(2, 2, -2, -2))
            if self.isChecked():
                color = self._active_color
            elif self._hover:
                color = theme.TEXT
            else:
                color = self._color
            if not self.isEnabled():
                color = theme.FAINT
        dpr = self.devicePixelRatioF()
        pm = icons.pixmap(self._icon, color, self._icon_size, max(1.0, dpr))
        x = (r.width() - self._icon_size) / 2
        y = (r.height() - self._icon_size) / 2
        if self.isDown() and not self._filled:
            y += 1
        p.drawPixmap(QRectF(x, y, self._icon_size, self._icon_size), pm, QRectF(pm.rect()))
        if self.isChecked() and not self._filled and self.isCheckable():
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(self._active_color))
            p.drawEllipse(QPointF(r.width() / 2, r.height() - 3), 2, 2)


class SeekBar(QWidget):
    """Thin progress bar; drag to seek, hover shows the time under the cursor."""
    seek_requested = Signal(float)
    preview = Signal(float)          # while dragging

    def __init__(self, parent=None, height=18):
        super().__init__(parent)
        self.setFixedHeight(height)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._duration = 0.0
        self._value = 0.0
        self._drag = None
        self._hover_x = None
        self.setToolTip(tr("Drag or click to jump to a moment in the song"))

    def set_duration(self, duration):
        self._duration = max(0.0, float(duration or 0.0))
        self.update()

    def set_value(self, value):
        if self._drag is None:
            v = float(value or 0.0)
            if abs(v - self._value) > 0.02:
                self._value = v
                self.update()

    def _x_to_value(self, x):
        w = max(1, self.width() - 12)
        frac = min(1.0, max(0.0, (x - 6) / w))
        return frac * self._duration

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._duration > 0:
            self._drag = self._x_to_value(event.position().x())
            self.preview.emit(self._drag)
            self.update()

    def mouseMoveEvent(self, event):
        self._hover_x = event.position().x()
        if self._drag is not None:
            self._drag = self._x_to_value(self._hover_x)
            self.preview.emit(self._drag)
        if self._duration > 0:
            self.setToolTip(fmt_time(self._x_to_value(self._hover_x)))
        self.update()

    def mouseReleaseEvent(self, event):
        if self._drag is not None:
            value = self._drag
            self._drag = None
            self._value = value
            self.seek_requested.emit(value)
            self.update()

    def leaveEvent(self, event):
        self._hover_x = None
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        active = self._hover_x is not None or self._drag is not None
        h = 5 if active else 4
        y = self.height() / 2
        x0, x1 = 6, self.width() - 6
        track = QRectF(x0, y - h / 2, x1 - x0, h)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 30))
        p.drawRoundedRect(track, h / 2, h / 2)
        value = self._drag if self._drag is not None else self._value
        frac = min(1.0, value / self._duration) if self._duration > 0 else 0.0
        fill = QRectF(x0, y - h / 2, (x1 - x0) * frac, h)
        grad = QLinearGradient(fill.topLeft(), fill.topRight())
        grad.setColorAt(0, QColor(theme.RED_DARK))
        grad.setColorAt(1, QColor(theme.RED_BRIGHT if active else theme.RED))
        p.setBrush(grad)
        p.drawRoundedRect(fill, h / 2, h / 2)
        if active and self._hover_x is not None and self._drag is None:
            hx = min(max(self._hover_x, x0), x1)
            p.setBrush(QColor(255, 255, 255, 40))
            p.drawRoundedRect(QRectF(x0, y - h / 2, hx - x0, h), h / 2, h / 2)
        if active and self._duration > 0:
            p.setBrush(QColor("#ffffff"))
            p.drawEllipse(QPointF(fill.right(), y), 6, 6)


class VolumeSlider(QWidget):
    value_changed = Signal(float)
    released = Signal()

    def __init__(self, parent=None, width=110):
        super().__init__(parent)
        self.setFixedSize(width, 20)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self._value = 0.8
        self._muted = False
        self._hover = False
        self._drag = False
        self.setToolTip(tr("Volume - drag, or scroll the mouse wheel"))

    def set_value(self, value, muted=False):
        self._value = min(1.0, max(0.0, value))
        self._muted = muted
        self.update()

    def value(self):
        return self._value

    def _emit_from(self, x):
        w = max(1, self.width() - 12)
        self._value = min(1.0, max(0.0, (x - 6) / w))
        self.setToolTip(tr("Volume {n}%", n=int(round(self._value * 100))))
        self.value_changed.emit(self._value)
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag = True
            self._emit_from(event.position().x())

    def mouseMoveEvent(self, event):
        if self._drag:
            self._emit_from(event.position().x())

    def mouseReleaseEvent(self, event):
        if self._drag:
            self._drag = False
            self.released.emit()

    def wheelEvent(self, event):
        step = 0.05 if event.angleDelta().y() > 0 else -0.05
        self._value = min(1.0, max(0.0, self._value + step))
        self.value_changed.emit(self._value)
        self.released.emit()
        self.update()

    def enterEvent(self, event):
        self._hover = True
        self.update()

    def leaveEvent(self, event):
        self._hover = False
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        y = self.height() / 2
        x0, x1 = 6, self.width() - 6
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 30))
        p.drawRoundedRect(QRectF(x0, y - 2, x1 - x0, 4), 2, 2)
        v = 0.0 if self._muted else self._value
        p.setBrush(QColor(theme.RED_BRIGHT if self._hover else theme.RED) if not self._muted else QColor(theme.FAINT))
        p.drawRoundedRect(QRectF(x0, y - 2, (x1 - x0) * v, 4), 2, 2)
        if self._hover or self._drag:
            p.setBrush(QColor("#ffffff"))
            p.drawEllipse(QPointF(x0 + (x1 - x0) * v, y), 5.5, 5.5)


class ElidedLabel(QLabel):
    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full = text
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setText(text)

    def setText(self, text):
        self._full = text or ""
        self._update_elide()

    def full_text(self):
        return self._full

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_elide()

    def _update_elide(self):
        fm = QFontMetrics(self.font())
        elided = fm.elidedText(self._full, Qt.ElideRight, max(10, self.width()))
        super().setText(elided)
        self.setToolTip(self._full if elided != self._full else "")


_logo_cache = {}


def _np_rgba(img):
    import numpy as np
    img = img.convertToFormat(QImage.Format_RGBA8888)
    h, w = img.height(), img.width()
    buf = np.frombuffer(img.constBits(), dtype=np.uint8, count=img.bytesPerLine() * h)
    return buf.reshape(h, img.bytesPerLine())[:, : w * 4].reshape(h, w, 4).copy()


def _from_np(arr):
    h, w = arr.shape[:2]
    import numpy as np
    arr = np.ascontiguousarray(arr)
    return QImage(arr.data, w, h, w * 4, QImage.Format_RGBA8888).copy()


def _crop_alpha(arr):
    import numpy as np
    ys, xs = np.nonzero(arr[..., 3] > 12)
    if len(xs):
        arr = arr[ys.min(): ys.max() + 1, xs.min(): xs.max() + 1]
    return arr


def logo_pixmap():
    """The 999 logo in the active theme's colour version (assets/logos)."""
    key = ("logo", theme.LOGO)
    pm = _logo_cache.get(key)
    if pm is None:
        path = os.path.join(paths.ASSETS_DIR, "logos", f"{theme.LOGO}.png")
        pm = QPixmap(path if os.path.isfile(path) else paths.LOGO_FILE)
        _logo_cache[key] = pm
    return pm


def logo_cropped():
    """The 999 logo without its transparent margins (so it reads well when small)."""
    key = ("cropped", theme.LOGO)
    pm = _logo_cache.get(key)
    if pm is not None:
        return pm
    img = logo_pixmap().toImage()
    try:
        pm = QPixmap.fromImage(_from_np(_crop_alpha(_np_rgba(img)))) if not img.isNull() else QPixmap()
    except Exception:
        pm = QPixmap.fromImage(img)
    _logo_cache[key] = pm
    return pm


def cat_pixmap(color=None):
    """The cat line art of a secret theme in any colour (null pixmap when it is locked)."""
    color = color or theme.RED
    key = ("cat", color)
    pm = _logo_cache.get(key)
    if pm is None:
        img = QImage.fromData(theme.FILES.get("cat.png", b""))
        if img.isNull():
            pm = QPixmap()
        else:
            try:
                arr = _np_rgba(img)
                c = QColor(color)
                arr[..., 0], arr[..., 1], arr[..., 2] = c.red(), c.green(), c.blue()
                pm = QPixmap.fromImage(_from_np(arr))
            except Exception:
                pm = QPixmap.fromImage(img)
        _logo_cache[key] = pm
    return pm


def brand_pixmap():
    """What the active theme shows as its logo: the 999 logo or the cat."""
    return cat_pixmap(theme.RED) if theme.BRAND == "cat" else logo_cropped()


class BrandLabel(QWidget):
    """[999 logo] PLAYER (or [cat] PLAYER in a theme with the cat) - the brand mark instead of the letters 'T9'."""

    def __init__(self, height=28, text_size=None, parent=None, spacing=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(spacing if spacing is not None else max(6, height // 4))
        logo = QLabel()
        is_cat = theme.BRAND == "cat"
        pm = brand_pixmap()
        if not pm.isNull():
            dpr = 2.0
            h = int(height * (1.25 if is_cat else 1.0))
            scaled = pm.scaledToHeight(int(h * dpr), Qt.SmoothTransformation)
            scaled.setDevicePixelRatio(dpr)
            logo.setPixmap(scaled)
            logo.setFixedSize(int(scaled.width() / dpr), h)
        logo.setToolTip(theme.label if is_cat else "999")
        lay.addWidget(logo, 0, Qt.AlignVCenter)
        word = QLabel(theme.title_text("PLAYER") if not is_cat else "Player")
        size = text_size or max(12, int(height * 0.62))
        if theme.TITLE_FONT != theme.FONT and theme.NAME != "999":
            word.setStyleSheet(f"color: {theme.TEXT}; {theme.title_css(int(size * 1.1))}")
        else:
            word.setStyleSheet(f"color: {theme.TEXT}; font-size: {size}px; font-weight: 800; "
                               f"letter-spacing: {max(1, size // 7)}px;")
        lay.addWidget(word, 0, Qt.AlignVCenter)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)


def paint_placeholder(p, rect, radius=10):
    """Theme gradient with a faded logo (or the cat) - used when a track has no cover."""
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    grad = QRadialGradient(rect.center(), max(rect.width(), rect.height()) * 0.75)
    grad.setColorAt(0, QColor(theme.PLACEHOLDER[0]))
    grad.setColorAt(1, QColor(theme.PLACEHOLDER[1]))
    p.fillPath(path, grad)
    mark = brand_pixmap() if theme.BRAND == "cat" else logo_pixmap()
    if not mark.isNull():
        side = min(rect.width(), rect.height()) * (0.62 if theme.BRAND == "cat" else 0.55)
        ratio = mark.height() / max(1, mark.width())
        target = QRectF(rect.center().x() - side / 2, rect.center().y() - side * ratio / 2, side, side * ratio)
        old = p.opacity()
        p.setOpacity(old * (0.5 if theme.BRAND == "cat" else 0.35))
        p.drawPixmap(target, mark, QRectF(mark.rect()))
        p.setOpacity(old)


class CoverWidget(QWidget):
    """Square cover with rounded corners, soft shadow and cross-fade on change."""
    clicked = Signal()

    def __init__(self, parent=None, radius=12, shadow=True):
        super().__init__(parent)
        self._radius = radius
        self._shadow = shadow
        self._pix = None
        self._old = None
        self._scaled = {}
        self._fade = 1.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(260)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_fade)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(48, 48)

    def set_image(self, image):
        """QImage / QPixmap / None."""
        new = None
        if image is not None:
            new = image if isinstance(image, QPixmap) else QPixmap.fromImage(image)
            if new.isNull():
                new = None
        self._old = self._pix
        self._pix = new
        self._scaled = {}
        self._anim.stop()
        self._fade = 0.0
        self._anim.start()

    def _on_fade(self, value):
        self._fade = float(value)
        if self._fade >= 1.0:
            self._old = None
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()

    def heightForWidth(self, w):
        return w

    def hasHeightForWidth(self):
        return True

    def cover_rect(self):
        side = min(self.width(), self.height()) - (16 if self._shadow else 0)
        side = max(10, side)
        return QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)

    def _scaled_for(self, pix, side):
        key = (pix.cacheKey(), int(side * self.devicePixelRatioF()))
        hit = self._scaled.get(key)
        if hit is None:
            px = key[1]
            hit = pix.scaled(px, px, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            hit.setDevicePixelRatio(self.devicePixelRatioF())
            if len(self._scaled) > 6:
                self._scaled.clear()
            self._scaled[key] = hit
        return hit

    def _draw(self, p, pix, rect, opacity):
        p.setOpacity(opacity)
        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)
        if pix is None:
            paint_placeholder(p, rect, self._radius)
            return
        scaled = self._scaled_for(pix, rect.width())
        p.save()
        p.setClipPath(path)
        sw = scaled.width() / scaled.devicePixelRatio()
        sh = scaled.height() / scaled.devicePixelRatio()
        target = QRectF(rect.center().x() - sw / 2, rect.center().y() - sh / 2, sw, sh)
        p.drawPixmap(target, scaled, QRectF(scaled.rect()))
        p.restore()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        rect = self.cover_rect()
        if self._shadow:
            for i, alpha in enumerate((34, 22, 12, 6)):
                grow = 2 + i * 3
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(0, 0, 0, alpha))
                p.drawRoundedRect(rect.adjusted(-grow, -grow + 4, grow, grow + 4),
                                  self._radius + grow, self._radius + grow)
        if self._old is not None and self._fade < 1.0:
            self._draw(p, self._old, rect, 1.0)
        self._draw(p, self._pix, rect, self._fade if self._old is not None or self._fade < 1.0 else 1.0)
        p.setOpacity(1.0)
        p.setPen(QPen(QColor(255, 255, 255, 18), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), self._radius, self._radius)


class Toast(QLabel):
    """Short message that fades in over the bottom of a window."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignCenter)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_message(self, text, level="info", ms=3800):
        border = {"error": theme.RED, "warning": "#b8860b"}.get(level, theme.RED_DARK)
        bg = QColor(theme.RAISED)
        self.setStyleSheet(
            f"background: rgba({bg.red()},{bg.green()},{bg.blue()},240); color: {theme.TEXT}; border: 1px solid {border};"
            "border-radius: 10px; padding: 9px 16px; font-size: 13px;")
        self.setText(text)
        parent = self.parentWidget()
        width = min(560, parent.width() - 40)
        self.setFixedWidth(max(200, width))
        self.adjustSize()
        bottom_margin = getattr(parent, "toast_bottom_margin", lambda: 100)()
        self.move((parent.width() - self.width()) // 2, parent.height() - self.height() - bottom_margin)
        self.raise_()
        self.show()
        self._timer.start(ms)


def bold_font(size, weight=QFont.DemiBold):
    f = QFont(theme.FONT)
    f.setPixelSize(size)
    f.setWeight(QFont.Weight(weight) if isinstance(weight, int) else weight)
    return f
