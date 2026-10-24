"""Theme scenery: pictures cut from the album covers (assets/theme_art), the 999 logos and
vector details (road, drips, stars, flowers, racing stripes ...). Themes that come in an encrypted
pack add their own scenes and animated layers through register_scene().

Every scene is painted once into a cached pixmap per size, so scrolling and animations
never repaint it from scratch.

    paint_sidebar(p, rect)    - the left sidebar (bigger pictures)
    paint_backdrop(p, rect)   - behind the song lists, grids and pages (faint watermark)
    paint_panel(p, rect)      - settings pages / mini player (small corner accent)
    paint_lyrics(p, rect)     - over the lyrics backdrop (very light)
"""

import math
import os
import random

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QLinearGradient, QBrush, QPainter, QPainterPath, QPen,
                           QPixmap, QRadialGradient)
from PySide6.QtWidgets import QStackedWidget, QWidget

from .. import paths, theme

_art_cache = {}

# scenes added by themes that come in a pack: decor id -> {"sidebar": fn(p, rect), "backdrop": ..., "panel": ...,
# "card": ..., "lyrics": ..., "lyrics_layer": widget factory, "window_layer": widget factory, "optional_layers": bool}
SCENES = {}


def register_scene(decor_id, **parts):
    SCENES[decor_id] = parts


def _scene(kind, part, p, rect):
    """Paint a registered scene part; True when the theme has one (the built-in branches are skipped then)."""
    fn = SCENES.get(kind, {}).get(part)
    if fn is None:
        return False
    try:
        fn(p, rect)
    except Exception:
        pass
    return True


def make_layer(where, parent):
    """An animated layer of the active theme ("lyrics" view or the "window"), or None."""
    factory = SCENES.get(theme.DECOR, {}).get(where + "_layer")
    if factory is None:
        return None
    try:
        return factory(parent)
    except Exception:
        return None


def has_optional_layers(decor_id):
    """True when the theme's animation can be switched off in the settings."""
    return bool(SCENES.get(decor_id, {}).get("optional_layers"))


def art(name):
    """A cut-out from theme_art (QPixmap, may be null)."""
    pm = _art_cache.get(name)
    if pm is None:
        pm = QPixmap(os.path.join(paths.ASSETS_DIR, "theme_art", name + ".png"))
        if pm.isNull() and name + ".png" in theme.FILES:          # pictures that came in a pack
            pm.loadFromData(theme.FILES[name + ".png"])
        _art_cache[name] = pm
    return pm


def _tinted(name, color):
    """Line art (dark strokes) recoloured, e.g. the cracked phone in sky blue."""
    key = (name, color)
    pm = _art_cache.get(key)
    if pm is None:
        src = art(name)
        pm = QPixmap(src.size())
        pm.fill(Qt.transparent)
        if not src.isNull():
            q = QPainter(pm)
            q.drawPixmap(0, 0, src)
            q.setCompositionMode(QPainter.CompositionMode_SourceIn)
            q.fillRect(pm.rect(), QColor(color))
            q.end()
        _art_cache[key] = pm
    return pm


def _draw(p, pm, x, y, w=None, h=None, opacity=1.0, anchor="topleft"):
    """Draw a pixmap keeping its aspect ratio (give w or h)."""
    if pm is None or pm.isNull():
        return QRectF()
    ratio = pm.height() / max(1, pm.width())
    if w is None and h is None:
        w = pm.width()
    if w is None:
        w = h / ratio
    if h is None:
        h = w * ratio
    if anchor == "bottomright":
        x, y = x - w, y - h
    elif anchor == "bottomleft":
        y = y - h
    elif anchor == "center":
        x, y = x - w / 2, y - h / 2
    elif anchor == "topright":
        x = x - w
    elif anchor == "bottomcenter":
        x, y = x - w / 2, y - h
    elif anchor == "topcenter":
        x = x - w / 2
    target = QRectF(x, y, w, h)
    old = p.opacity()
    p.setOpacity(old * opacity)
    p.drawPixmap(target, pm, QRectF(pm.rect()))
    p.setOpacity(old)
    return target


def _color(c, alpha):
    col = QColor(c)
    col.setAlpha(int(max(0, min(255, alpha))))
    return col


# ============================================================================ vector shapes

def sparkle(p, cx, cy, r, color, alpha=255):
    """Four-point star."""
    path = QPainterPath()
    for i in range(8):
        ang = math.pi / 4 * i - math.pi / 2
        rr = r if i % 2 == 0 else r * 0.22
        pt = QPointF(cx + math.cos(ang) * rr, cy + math.sin(ang) * rr)
        path.moveTo(pt) if i == 0 else path.lineTo(pt)
    path.closeSubpath()
    p.fillPath(path, _color(color, alpha))


def crescent(p, cx, cy, r, color, alpha=255):
    full = QPainterPath()
    full.addEllipse(QPointF(cx, cy), r, r)
    cut = QPainterPath()
    cut.addEllipse(QPointF(cx + r * 0.45, cy - r * 0.2), r * 0.92, r * 0.92)
    p.fillPath(full.subtracted(cut), _color(color, alpha))


def drips(p, rect, color, alpha=200, seed=1, depth=40, count=None):
    """Paint dripping from the top edge (WOD purple drank ...)."""
    rng = random.Random(seed)
    w = rect.width()
    path = QPainterPath(QPointF(rect.left(), rect.top()))
    x = rect.left()
    base = rect.top() + depth * 0.18
    path.lineTo(x, base)
    n = count or max(3, int(w / 34))
    step = w / n
    for i in range(n):
        x0 = rect.left() + i * step
        dw = rng.uniform(step * 0.25, step * 0.5)
        dx = x0 + rng.uniform(step * 0.15, step - dw)
        dl = rng.uniform(depth * 0.35, depth)
        path.lineTo(dx, base)
        path.cubicTo(dx + dw * 0.05, base + dl * 0.6, dx + dw * 0.05, base + dl, dx + dw / 2, base + dl)
        path.cubicTo(dx + dw * 0.95, base + dl, dx + dw * 0.95, base + dl * 0.6, dx + dw, base)
    path.lineTo(rect.right(), base)
    path.lineTo(rect.right(), rect.top())
    path.closeSubpath()
    grad = QLinearGradient(0, rect.top(), 0, rect.top() + depth * 1.2)
    grad.setColorAt(0, _color(color, alpha))
    grad.setColorAt(1, _color(QColor(color).darker(140), alpha))
    p.fillPath(path, grad)


def flower(p, cx, cy, r, petal, center, alpha):
    p.setPen(Qt.NoPen)
    p.setBrush(_color(petal, alpha))
    for i in range(5):
        ang = math.tau / 5 * i
        p.drawEllipse(QPointF(cx + math.cos(ang) * r * 0.55, cy + math.sin(ang) * r * 0.55), r * 0.5, r * 0.5)
    p.setBrush(_color(center, alpha))
    p.drawEllipse(QPointF(cx, cy), r * 0.32, r * 0.32)


def butterfly(p, cx, cy, size, angle=0.0, alpha=255, c1="#ff8a1f", c2="#ffd27a", flap=0.0):
    """Monarch butterfly seen from above: pointed fore wings, round hind wings, black rims with white dots."""
    p.save()
    p.translate(cx, cy)
    p.rotate(angle)
    p.scale(size / 100.0, size / 100.0)          # drawn on a 100 x 100 grid
    ink = _color("#1a0904", alpha)
    open_ = max(0.3, 1.0 - abs(flap))
    for side in (-1, 1):
        p.save()
        p.scale(side * open_, 1)
        fore = QPainterPath()
        fore.moveTo(3, -4)
        fore.cubicTo(14, -30, 34, -46, 50, -44)
        fore.cubicTo(54, -36, 52, -22, 44, -10)
        fore.cubicTo(32, 0, 14, 2, 3, -1)
        hind = QPainterPath()
        hind.moveTo(3, 1)
        hind.cubicTo(18, 0, 40, 4, 40, 18)
        hind.cubicTo(40, 32, 22, 42, 12, 38)
        hind.cubicTo(6, 30, 3, 14, 3, 1)
        for path, centre in ((hind, QPointF(16, 14)), (fore, QPointF(22, -20))):
            grad = QRadialGradient(centre, 36)
            grad.setColorAt(0, _color(c2, alpha))
            grad.setColorAt(0.55, _color(c1, alpha))
            grad.setColorAt(1, _color("#c4480a", alpha))
            p.setBrush(grad)
            p.setPen(QPen(ink, 4.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(path)
        p.setPen(QPen(_color("#1a0904", alpha * 0.7), 1.8, Qt.SolidLine, Qt.RoundCap))
        for x2, y2 in ((44, -38), (40, -18), (24, -6)):
            p.drawLine(QPointF(4, -3), QPointF(x2, y2))
        for x2, y2 in ((36, 16), (22, 34)):
            p.drawLine(QPointF(4, 2), QPointF(x2, y2))
        p.setPen(Qt.NoPen)
        p.setBrush(_color("#fff6e8", alpha * 0.9))
        for x, y in ((47, -40), (50, -33), (49, -25), (38, 24), (30, 33), (19, 37)):
            p.drawEllipse(QPointF(x, y), 1.6, 1.6)
        p.restore()
    p.setPen(Qt.NoPen)
    p.setBrush(ink)
    p.drawRoundedRect(QRectF(-3, -14, 6, 40), 3, 3)
    p.drawEllipse(QPointF(0, -16), 4, 4)
    p.setPen(QPen(ink, 1.8, Qt.SolidLine, Qt.RoundCap))
    p.setBrush(Qt.NoBrush)
    for side in (-1, 1):
        p.drawLine(QPointF(0, -18), QPointF(side * 10, -34))
        p.drawEllipse(QPointF(side * 10, -34), 1.5, 1.5)
    p.restore()


def meteor(p, x, y, length, angle_deg, alpha=255, color="#fff2c8"):
    """Falling star: a glowing head with a fading tail behind it."""
    a = math.radians(angle_deg)
    tail = QPointF(x - math.cos(a) * length, y - math.sin(a) * length)
    grad = QLinearGradient(tail, QPointF(x, y))
    grad.setColorAt(0, _color(color, 0))
    grad.setColorAt(1, _color(color, alpha))
    p.setPen(QPen(QBrush(grad), max(1.0, length / 60), Qt.SolidLine, Qt.RoundCap))
    p.drawLine(tail, QPointF(x, y))
    r = length * 0.09 + 3
    glow = QRadialGradient(QPointF(x, y), r)
    glow.setColorAt(0, _color("#ffffff", alpha))
    glow.setColorAt(0.4, _color(color, alpha * 0.6))
    glow.setColorAt(1, _color(color, 0))
    p.setPen(Qt.NoPen)
    p.setBrush(glow)
    p.drawEllipse(QPointF(x, y), r, r)


def feather(p, cx, cy, size, angle=0.0, alpha=255, color="#fff7f0"):
    """A small white angel feather."""
    p.save()
    p.translate(cx, cy)
    p.rotate(angle)
    vane = QPainterPath()
    vane.moveTo(0, -size * 0.5)
    vane.cubicTo(size * 0.22, -size * 0.35, size * 0.2, size * 0.2, 0, size * 0.38)
    vane.cubicTo(-size * 0.2, size * 0.2, -size * 0.2, -size * 0.3, 0, -size * 0.5)
    grad = QLinearGradient(QPointF(-size * 0.2, 0), QPointF(size * 0.2, 0))
    grad.setColorAt(0, _color(color, alpha * 0.55))
    grad.setColorAt(0.5, _color(color, alpha))
    grad.setColorAt(1, _color(color, alpha * 0.55))
    p.setPen(Qt.NoPen)
    p.setBrush(grad)
    p.drawPath(vane)
    p.setPen(QPen(_color("#d9b8c8", alpha), max(0.6, size * 0.03)))
    p.drawLine(QPointF(0, -size * 0.45), QPointF(0, size * 0.55))
    p.restore()


def _lnd_sky(p, rect, rng, butterflies, meteors, alpha, feathers=0):
    """Butterflies, falling stars and feathers scattered over a rect (Legends Never Die)."""
    for _ in range(meteors):
        x = rng.uniform(rect.left() + rect.width() * 0.1, rect.right())
        y = rng.uniform(rect.top(), rect.top() + rect.height() * 0.6)
        meteor(p, x, y, rng.uniform(40, 90), rng.uniform(58, 72), alpha)
    for _ in range(feathers):
        feather(p, rng.uniform(rect.left() + 10, rect.right() - 10), rng.uniform(rect.top() + 10, rect.bottom() - 10),
                rng.uniform(14, 24), rng.uniform(-60, 60), alpha * 0.7)
    for _ in range(butterflies):
        butterfly(p, rng.uniform(rect.left() + 14, rect.right() - 14), rng.uniform(rect.top() + 14, rect.bottom() - 14),
                  rng.uniform(26, 44), rng.uniform(-35, 35), alpha, flap=rng.uniform(-0.4, 0.2))


def murakami_flower(p, cx, cy, r, alpha=255, seed=0, angle=0.0):
    """Smiling rainbow flower (Takashi Murakami style, as on The Party Never Ends cover)."""
    colors = ("#ff3b3b", "#ff8a1f", "#ffd21f", "#7dde3a", "#22c1e8", "#3b6bff", "#a64dff", "#ff4fc8",
              "#ff3b3b", "#ffd21f", "#22c1e8", "#a64dff")
    ink = _color("#141018", alpha)
    p.save()
    p.translate(cx, cy)
    p.rotate(angle)
    p.setPen(QPen(ink, max(0.8, r * 0.05)))
    for i in range(12):
        a = math.radians(i * 30)
        p.setBrush(_color(colors[(i + seed) % len(colors)], alpha))
        p.drawEllipse(QPointF(math.cos(a) * r * 0.66, math.sin(a) * r * 0.66), r * 0.34, r * 0.34)
    p.setBrush(_color("#ffe14a", alpha))
    p.drawEllipse(QPointF(0, 0), r * 0.5, r * 0.5)
    p.setPen(Qt.NoPen)
    p.setBrush(ink)
    for x in (-0.17, 0.17):
        p.drawEllipse(QPointF(r * x, -r * 0.12), r * 0.06, r * 0.09)
    mouth = QPainterPath()
    mouth.moveTo(-r * 0.3, r * 0.02)
    mouth.cubicTo(-r * 0.22, r * 0.42, r * 0.22, r * 0.42, r * 0.3, r * 0.02)
    mouth.closeSubpath()
    p.setBrush(_color("#e8264a", alpha))
    p.setPen(QPen(ink, max(0.8, r * 0.04)))
    p.drawPath(mouth)
    p.setPen(Qt.NoPen)
    p.setBrush(_color("#ff9ac8", alpha * 0.8))
    for x in (-0.33, 0.33):
        p.drawEllipse(QPointF(r * x, r * 0.08), r * 0.07, r * 0.05)
    p.restore()


def _galaxy(p, rect, alpha):
    """Soft purple / pink nebula clouds."""
    for cx, cy, rad, col in ((0.2, 0.25, 0.6, "#b03cff"), (0.8, 0.6, 0.55, "#ff3fc8"), (0.45, 0.9, 0.5, "#3b6bff")):
        g = QRadialGradient(QPointF(rect.left() + rect.width() * cx, rect.top() + rect.height() * cy),
                            max(rect.width(), rect.height()) * rad)
        g.setColorAt(0, _color(col, alpha))
        g.setColorAt(1, _color(col, 0))
        p.fillRect(rect, g)


def checkered(p, rect, alpha, cell=8):
    p.setPen(Qt.NoPen)
    rows = max(1, int(rect.height() / cell))
    cols = int(rect.width() / cell) + 1
    for r in range(rows):
        for c in range(cols):
            if (r + c) % 2 == 0:
                p.fillRect(QRectF(rect.left() + c * cell, rect.top() + r * cell, cell, cell), _color("#ffffff", alpha))


def racing_stripes(p, rect, color, alpha, angle=-62, count=3):
    p.save()
    p.setClipRect(rect)
    p.translate(rect.center())
    p.rotate(angle)
    w = max(rect.width(), rect.height()) * 2
    for i in range(count):
        p.fillRect(QRectF(-w / 2, -30 + i * 16, w, 9 if i != 1 else 4),
                   _color(color if i != 1 else "#d9d4cc", alpha))
    p.restore()


def road(p, rect, alpha):
    """Asphalt band with a dashed middle line, slightly tilted like the cover."""
    p.save()
    p.setClipRect(rect)
    band = QPainterPath()
    band.moveTo(rect.left() - 20, rect.top() + rect.height() * 0.62)
    band.lineTo(rect.right() + 20, rect.top() + rect.height() * 0.30)
    band.lineTo(rect.right() + 20, rect.top() + rect.height() * 0.72)
    band.lineTo(rect.left() - 20, rect.top() + rect.height() * 0.98)
    band.closeSubpath()
    grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    grad.setColorAt(0, _color("#3a4652", alpha))
    grad.setColorAt(1, _color("#1c242c", alpha))
    p.fillPath(band, grad)
    pen = QPen(_color("#ffffff", alpha * 0.7), 3, Qt.CustomDashLine, Qt.FlatCap)
    pen.setDashPattern([5, 4])
    p.setPen(pen)
    p.drawLine(QPointF(rect.left() - 20, rect.top() + rect.height() * 0.82),
               QPointF(rect.right() + 20, rect.top() + rect.height() * 0.52))
    # guard rail
    p.setPen(QPen(_color("#c9d6e2", alpha * 0.6), 2))
    p.drawLine(QPointF(rect.left() - 20, rect.top() + rect.height() * 0.56),
               QPointF(rect.right() + 20, rect.top() + rect.height() * 0.24))
    p.restore()


def _stars(p, rect, rng, count, color, alpha, big=0.25, r=(3, 7)):
    for _ in range(count):
        x, y = rng.uniform(rect.left(), rect.right()), rng.uniform(rect.top(), rect.bottom())
        if rng.random() < big:
            sparkle(p, x, y, rng.uniform(*r), color, alpha)
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(_color(color, alpha * rng.uniform(0.4, 1)))
            p.drawEllipse(QPointF(x, y), 1.1, 1.1)


# ============================================================================ scenes

def paint_sidebar(p, rect):
    """Bigger pictures in the lower part of the sidebar."""
    kind = theme.DECOR
    rng = random.Random(999)
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    p.setClipRect(rect)
    w, b = rect.width(), rect.bottom()
    if _scene(kind, "sidebar", p, rect):
        pass
    elif kind == "999":
        glow = QRadialGradient(QPointF(rect.center().x(), b), w * 0.9)
        glow.setColorAt(0, _color(theme.RED, 50))
        glow.setColorAt(1, _color(theme.RED, 0))
        p.fillRect(rect, glow)
        from .widgets import logo_cropped
        _draw(p, art("t999_figure"), rect.center().x(), b - 10, w=w * 0.95, opacity=0.75, anchor="bottomcenter")
        _draw(p, logo_cropped(), rect.center().x(), b - 30, w=w * 0.5, opacity=0.5, anchor="bottomcenter")
    elif kind == "gbgr":
        _stars(p, QRectF(rect.left(), rect.top(), w, rect.height() * 0.45), rng, 18, "#ffffff", 120)
        crescent(p, rect.right() - 34, rect.top() + 28, 12, "#f6e27a", 160)
        road_rect = QRectF(rect.left(), b - 230, w, 220)
        road(p, road_rect, 230)
        _draw(p, art("gbgr_car"), rect.left() + w * 0.56, b - 52, w=w * 0.7, anchor="bottomcenter")
        _draw(p, art("gbgr_girl"), rect.left() + 12, b - 128, h=86, anchor="bottomleft")
    elif kind == "wod":
        for _ in range(7):
            flower(p, rng.uniform(rect.left() + 14, rect.right() - 14), rng.uniform(rect.top() + 70, b - 200),
                   rng.uniform(6, 10), rng.choice(("#c78bff", "#ffcf3f", "#ff9ec7")), "#7a4a1f", 120)
        _draw(p, art("wod_planet"), rect.center().x(), b - 50, w=w * 0.66, opacity=0.95, anchor="bottomcenter")
    elif kind == "outsiders":
        _stars(p, rect, rng, 26, "#ffffff", 150, big=0.15)
        _draw(p, art("outsiders_sparkles"), rect.left() + 12, rect.top() + 18, w=58, opacity=0.8)
        _draw(p, art("outsiders_doves"), rect.right() - 6, rect.top() + rect.height() * 0.45, w=w * 0.82,
              opacity=0.95, anchor="bottomright")
        _draw(p, art("outsiders_birds"), rect.left() + 24, rect.top() + rect.height() * 0.52, w=34, opacity=0.8)
        _draw(p, art("outsiders_cd"), rect.right() - 24, b - 60, w=62, opacity=0.75, anchor="bottomright")
    elif kind == "drfl":
        glow = QRadialGradient(QPointF(rect.center().x(), b), w)
        glow.setColorAt(0, _color("#ff4a12", 70))
        glow.setColorAt(1, _color("#ff4a12", 0))
        p.fillRect(rect, glow)
        racing_stripes(p, QRectF(rect.left(), rect.top(), w, rect.height() * 0.6), theme.RED, 110)
        checkered(p, QRectF(rect.left(), b - 46, w, 16), 28)
        _draw(p, art("drfl_car_left"), rect.center().x(), b - 50, w=w * 0.9, opacity=0.55, anchor="bottomcenter")
        _draw(p, art("drfl_life"), rect.left() + 14, rect.top() + rect.height() * 0.55, w=50, opacity=0.95)
        _draw(p, art("drfl_pillbox"), rect.right() - 14, rect.top() + rect.height() * 0.55, w=48, opacity=0.95,
              anchor="topright")
        for _ in range(16):
            p.setPen(Qt.NoPen)
            p.setBrush(_color(rng.choice(("#ff8a3d", "#ffd27a", "#ff5a1f")), rng.randint(60, 160)))
            p.drawEllipse(QPointF(rng.uniform(rect.left(), rect.right()), rng.uniform(rect.top(), b - 60)), 1.4, 1.4)
    elif kind == "tpne":
        _galaxy(p, rect, 70)
        _stars(p, rect, rng, 30, "#ffffff", 170, big=0.3)
        _draw(p, art("tpne_planet"), rect.center().x(), rect.top() + 34, w=w * 0.92, opacity=0.95, anchor="topcenter")
        for fx, fy, fr, seed in ((0.22, 0.62, 30, 0), (0.7, 0.72, 40, 3), (0.32, 0.88, 46, 6), (0.86, 0.95, 26, 2)):
            murakami_flower(p, rect.left() + w * fx, rect.top() + rect.height() * fy, fr, 235, seed, fx * 40)
    elif kind == "lnd":
        glow = QRadialGradient(QPointF(rect.center().x(), b - rect.height() * 0.25), w)
        glow.setColorAt(0, _color("#ff7fae", 70))
        glow.setColorAt(1, _color("#ff7fae", 0))
        p.fillRect(rect, glow)
        _stars(p, QRectF(rect.left(), rect.top(), w, rect.height() * 0.5), rng, 18, "#fff2c8", 150, big=0.3)
        _draw(p, art("lnd_field"), rect.center().x(), b + 4, w=w * 1.05, opacity=0.9, anchor="bottomcenter")
        _lnd_sky(p, QRectF(rect.left(), rect.top() + 20, w, rect.height() * 0.45), rng, 4, 3, 220, feathers=2)
    p.restore()


def paint_backdrop(p, rect):
    """Faint art behind the content pages (song lists, grids, album / artist pages)."""
    kind = theme.DECOR
    rng = random.Random(9)
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    w, h = rect.width(), rect.height()
    if _scene(kind, "backdrop", p, rect):
        pass
    elif kind == "999":
        glow = QRadialGradient(QPointF(rect.right(), rect.bottom()), w * 0.6)
        glow.setColorAt(0, _color(theme.RED, 26))
        glow.setColorAt(1, _color(theme.RED, 0))
        p.fillRect(rect, glow)
        _draw(p, art("t999_cover"), rect.right() + w * 0.02, rect.bottom() + h * 0.04, h=h * 0.95, opacity=0.13,
              anchor="bottomright")
    elif kind == "gbgr":
        _draw(p, _tinted("gbgr_lineart", "#7cc8f0"), rect.right() - w * 0.03, rect.bottom() - h * 0.02,
              h=h * 0.92, opacity=0.08, anchor="bottomright")
        _stars(p, QRectF(rect.left(), rect.top(), w, h * 0.4), rng, 30, "#ffffff", 35)
    elif kind == "wod":
        drips(p, QRectF(rect.left(), rect.top(), w, 30), theme.RED_DARK, 90, seed=11, depth=26, count=max(6, int(w / 70)))
        _draw(p, art("wod_planet"), rect.right() - w * 0.18, rect.center().y() + h * 0.08, h=h * 0.72,
              opacity=0.07, anchor="center")
        for _ in range(9):
            flower(p, rng.uniform(rect.left(), rect.right()), rng.uniform(rect.top() + 40, rect.bottom()),
                   rng.uniform(8, 14), rng.choice(("#c78bff", "#ffcf3f", "#ff9ec7")), "#7a4a1f", 22)
    elif kind == "outsiders":
        _stars(p, rect, rng, 60, "#ffffff", 45, big=0.12)
        _draw(p, art("outsiders_boy"), rect.center().x() + w * 0.12, rect.bottom(), h=h * 0.55, opacity=0.07,
              anchor="bottomcenter")
        _draw(p, art("outsiders_title"), rect.left() + w * 0.06, rect.bottom() - h * 0.05, w=w * 0.3, opacity=0.06,
              anchor="bottomleft")
        _draw(p, art("outsiders_doves"), rect.right() - w * 0.04, rect.top() + h * 0.08, w=w * 0.22, opacity=0.06,
              anchor="topright")
    elif kind == "drfl":
        glow = QRadialGradient(QPointF(rect.center().x(), rect.bottom() + h * 0.2), w * 0.7)
        glow.setColorAt(0, _color("#ff4a12", 40))
        glow.setColorAt(1, _color("#ff4a12", 0))
        p.fillRect(rect, glow)
        _draw(p, art("drfl_title"), rect.right() - w * 0.04, rect.bottom() - h * 0.05, w=w * 0.42, opacity=0.08,
              anchor="bottomright")
        _draw(p, art("drfl_car_right"), rect.left() + w * 0.02, rect.bottom() - h * 0.02, w=w * 0.26, opacity=0.06,
              anchor="bottomleft")
        racing_stripes(p, QRectF(rect.right() - w * 0.35, rect.top(), w * 0.35, h * 0.5), theme.RED, 14)
    elif kind == "tpne":
        _galaxy(p, rect, 22)
        _stars(p, rect, rng, 70, "#ffffff", 50, big=0.2)
        _draw(p, art("tpne_cover"), rect.right() + w * 0.02, rect.bottom() + h * 0.04, h=h * 0.95, opacity=0.1,
              anchor="bottomright")
        _draw(p, art("tpne_title"), rect.left() + w * 0.04, rect.bottom() - h * 0.04, w=min(w * 0.3, 420), opacity=0.06,
              anchor="bottomleft")
        for _ in range(5):
            murakami_flower(p, rng.uniform(rect.left() + w * 0.3, rect.right() - 30),
                            rng.uniform(rect.top() + 30, rect.bottom() - 30), rng.uniform(16, 30), 75,
                            rng.randint(0, 11), rng.uniform(0, 30))
    elif kind == "lnd":
        glow = QRadialGradient(QPointF(rect.right() - w * 0.15, rect.bottom()), w * 0.6)
        glow.setColorAt(0, _color("#ff7fae", 34))
        glow.setColorAt(1, _color("#ff7fae", 0))
        p.fillRect(rect, glow)
        _draw(p, art("lnd_portrait"), rect.right() + w * 0.02, rect.bottom() + h * 0.04, h=h * 0.95, opacity=0.11,
              anchor="bottomright")
        _stars(p, rect, rng, 45, "#fff2c8", 45, big=0.25)
        _lnd_sky(p, QRectF(rect.left() + w * 0.3, rect.top(), w * 0.7, h * 0.7), rng, 5, 5, 95, feathers=4)
    p.restore()


def paint_panel(p, rect):
    """A small accent in the bottom-right corner (settings pages, mini player)."""
    kind = theme.DECOR
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    r, b = rect.right() - 12, rect.bottom() - 12
    if _scene(kind, "panel", p, rect):
        pass
    elif kind == "999":
        _draw(p, art("t999_figure"), r, b + 12, w=120, opacity=0.35, anchor="bottomright")
    elif kind == "gbgr":
        _draw(p, art("gbgr_car"), r, b, w=150, opacity=0.35, anchor="bottomright")
    elif kind == "wod":
        _draw(p, art("wod_planet"), r, b, w=95, opacity=0.35, anchor="bottomright")
    elif kind == "outsiders":
        _draw(p, art("outsiders_doves"), r, b - 20, w=160, opacity=0.3, anchor="bottomright")
    elif kind == "drfl":
        _draw(p, art("drfl_life"), r, b, w=46, opacity=0.6, anchor="bottomright")
        _draw(p, art("drfl_pillbox"), r - 56, b, w=46, opacity=0.6, anchor="bottomright")
    elif kind == "tpne":
        murakami_flower(p, r - 40, b - 40, 40, 170, 0)
        murakami_flower(p, r - 112, b - 22, 22, 140, 5, 15)
        _draw(p, art("tpne_planet"), r - 150, b - 70, w=120, opacity=0.35, anchor="bottomright")
    elif kind == "lnd":
        meteor(p, r - 120, b - 120, 70, 64, 120)
        butterfly(p, r - 30, b - 40, 34, 18, 170)
        butterfly(p, r - 90, b - 80, 22, -20, 130, flap=0.3)
        feather(p, r - 150, b - 30, 22, 40, 110)
    p.restore()


def card_art(p, name, rect):
    """Little picture for a theme's card in the settings."""
    decor = theme.THEMES.get(name, {}).get("DECOR")
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    r, b = rect.right() - 6, rect.bottom() - 6
    if _scene(decor, "card", p, rect):
        pass
    elif name == "999":
        _draw(p, QPixmap(os.path.join(paths.ASSETS_DIR, "logos", "06_red_blood.png")), r + 6, b + 10, w=58,
              opacity=0.9, anchor="bottomright")
    elif name == "gbgr":
        _draw(p, art("gbgr_car"), r, b - 34, w=62, opacity=0.95, anchor="bottomright")
    elif name == "wod":
        _draw(p, art("wod_planet"), r, b - 30, w=40, opacity=0.95, anchor="bottomright")
    elif name == "outsiders":
        _draw(p, art("outsiders_doves"), r, b - 30, w=60, opacity=0.95, anchor="bottomright")
    elif name == "drfl":
        _draw(p, art("drfl_life"), r, b - 36, w=26, opacity=0.95, anchor="bottomright")
        _draw(p, art("drfl_pillbox"), r - 30, b - 36, w=26, opacity=0.95, anchor="bottomright")
    elif name == "tpne":
        murakami_flower(p, r - 18, b - 44, 18, 255, 0)
        murakami_flower(p, r - 48, b - 38, 11, 240, 4, 20)
    elif name == "lnd":
        meteor(p, r - 40, b - 64, 34, 64, 200)
        butterfly(p, r - 14, b - 42, 22, 15, 240)
        butterfly(p, r - 44, b - 36, 14, -20, 220, flap=0.3)


def paint_lyrics(p, rect):
    """Light touches over the lyrics backdrop."""
    kind = theme.DECOR
    rng = random.Random(4)
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    if _scene(kind, "lyrics", p, rect):
        pass
    elif kind == "wod":
        drips(p, QRectF(rect.left(), rect.top(), rect.width(), 26), theme.RED_DARK, 110, seed=8, depth=24,
              count=max(8, int(rect.width() / 70)))
    elif kind == "outsiders":
        _stars(p, rect, rng, 40, "#ffffff", 70, big=0.2)
    elif kind == "drfl":
        glow = QRadialGradient(QPointF(rect.center().x(), rect.bottom() + 80), rect.width() * 0.7)
        glow.setColorAt(0, _color("#ff4a12", 60))
        glow.setColorAt(1, _color("#ff4a12", 0))
        p.fillRect(rect, glow)
    elif kind == "tpne":
        _galaxy(p, rect, 30)
        _stars(p, rect, rng, 40, "#ffffff", 70, big=0.25)
        for _ in range(4):
            murakami_flower(p, rng.uniform(rect.left() + 40, rect.right() - 40),
                            rng.uniform(rect.top() + 30, rect.top() + rect.height() * 0.4), rng.uniform(14, 24), 80,
                            rng.randint(0, 11))
    elif kind == "lnd":
        _stars(p, rect, rng, 30, "#fff2c8", 60, big=0.3)
        _lnd_sky(p, QRectF(rect.left(), rect.top(), rect.width(), rect.height() * 0.5), rng, 4, 4, 140)
    elif kind == "gbgr":
        _stars(p, QRectF(rect.left(), rect.top(), rect.width(), rect.height() * 0.4), rng, 30, "#ffffff", 60)
    p.restore()


# ============================================================================ widgets

class _Cached:
    """Keeps one rendered pixmap per size."""

    def __init__(self, fn):
        self.fn = fn
        self.pm = None

    def get(self, size, dpr):
        if self.pm is None or self.pm.size() != size * dpr:
            pm = QPixmap(size * dpr)
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.transparent)
            q = QPainter(pm)
            self.fn(q, QRectF(0, 0, size.width(), size.height()))
            q.end()
            self.pm = pm
        return self.pm


class DecorBackground(QWidget):
    """The sidebar: theme colour + scenery in the lower part."""

    def __init__(self, parent=None, area=(0.55, 1.0)):
        super().__init__(parent)
        self._area = area
        self._cache = _Cached(self._paint)

    def _paint(self, p, rect):
        if theme.DECOR == "wod":       # purple drank dripping from the very top
            p.setRenderHint(QPainter.Antialiasing)
            drips(p, QRectF(0, 0, rect.width(), 34), theme.RED_DARK, 170, seed=3, depth=30, count=6)
        top = rect.height() * self._area[0]
        height = rect.height() * self._area[1] - top
        dpr = p.device().devicePixelRatioF() if p.device() else 1.0
        layer = QPixmap(int(rect.width() * dpr), int(height * dpr))
        layer.setDevicePixelRatio(dpr)
        layer.fill(Qt.transparent)
        q = QPainter(layer)
        paint_sidebar(q, QRectF(0, 0, rect.width(), height))
        q.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        fade = QLinearGradient(0, 0, 0, height)
        edge_top = min(0.3, 90 / max(1.0, height))
        edge_bottom = min(0.15, 26 / max(1.0, height))
        fade.setColorAt(0, QColor(0, 0, 0, 0))
        fade.setColorAt(edge_top, QColor(0, 0, 0, 255))
        fade.setColorAt(1 - edge_bottom, QColor(0, 0, 0, 255))
        fade.setColorAt(1, QColor(0, 0, 0, 0))
        q.fillRect(QRectF(0, 0, rect.width(), height), fade)
        q.end()
        p.drawPixmap(QPointF(0, top), layer)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(theme.SIDEBAR))
        if theme.DECOR != "none":
            p.drawPixmap(0, 0, self._cache.get(self.size(), self.devicePixelRatioF()))


class BackdropStack(QStackedWidget):
    """Page stack that paints the theme background + watermark behind transparent pages."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cache = _Cached(paint_backdrop)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(theme.BG))
        p.drawPixmap(0, 0, self._cache.get(self.size(), self.devicePixelRatioF()))


class DecorPage(QWidget):
    """A settings page with a small theme accent in the corner."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cache = _Cached(paint_panel)

    def paintEvent(self, event):
        from PySide6.QtWidgets import QStyle, QStyleOption
        opt = QStyleOption()
        opt.initFrom(self)
        p = QPainter(self)
        self.style().drawPrimitive(QStyle.PE_Widget, opt, p, self)
        p.drawPixmap(0, 0, self._cache.get(self.size(), self.devicePixelRatioF()))


def lyrics_background(p, rect):
    """Backdrop for the lyrics view when there is no cover (theme gradient)."""
    grad = QLinearGradient(0, 0, rect.width(), rect.height())
    grad.setColorAt(0, QColor(theme.LYR_BG[0]))
    grad.setColorAt(0.55, QColor(theme.LYR_BG[1]))
    grad.setColorAt(1, QColor(theme.LYR_BG[2]))
    p.fillRect(rect, grad)
