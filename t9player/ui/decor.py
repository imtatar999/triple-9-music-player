"""Theme scenery: pictures cut from the album covers (assets/theme_art), the 999 logos and
vector details (road, drips, bats, moon, stars, racing stripes, code rain ...).

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


def art(name):
    """A cut-out from theme_art (QPixmap, may be null)."""
    pm = _art_cache.get(name)
    if pm is None:
        pm = QPixmap(os.path.join(paths.ASSETS_DIR, "theme_art", name + ".png"))
        if pm.isNull() and name + ".png" in theme.FILES:          # pictures of an unlocked secret theme
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


def bat(p, cx, cy, size, color, alpha=255, flap=0.0):
    """Little bat silhouette."""
    s = size / 2.0
    lift = flap * s * 0.35
    path = QPainterPath(QPointF(cx, cy - s * 0.15))
    path.cubicTo(cx + s * 0.25, cy - s * 0.55 - lift, cx + s * 0.7, cy - s * 0.7 - lift, cx + s, cy - s * 0.35 - lift)
    path.cubicTo(cx + s * 0.85, cy - s * 0.05, cx + s * 0.8, cy + s * 0.1, cx + s * 0.62, cy + s * 0.2)
    path.cubicTo(cx + s * 0.55, cy + s * 0.05, cx + s * 0.45, cy + s * 0.05, cx + s * 0.35, cy + s * 0.22)
    path.cubicTo(cx + s * 0.28, cy + s * 0.08, cx + s * 0.18, cy + s * 0.08, cx + s * 0.12, cy + s * 0.3)
    path.lineTo(cx, cy + s * 0.12)
    path.lineTo(cx - s * 0.12, cy + s * 0.3)
    path.cubicTo(cx - s * 0.18, cy + s * 0.08, cx - s * 0.28, cy + s * 0.08, cx - s * 0.35, cy + s * 0.22)
    path.cubicTo(cx - s * 0.45, cy + s * 0.05, cx - s * 0.55, cy + s * 0.05, cx - s * 0.62, cy + s * 0.2)
    path.cubicTo(cx - s * 0.8, cy + s * 0.1, cx - s * 0.85, cy - s * 0.05, cx - s, cy - s * 0.35 - lift)
    path.cubicTo(cx - s * 0.7, cy - s * 0.7 - lift, cx - s * 0.25, cy - s * 0.55 - lift, cx, cy - s * 0.15)
    p.fillPath(path, _color(color, alpha))
    # ears
    ear = QPainterPath(QPointF(cx - s * 0.12, cy - s * 0.12))
    ear.lineTo(cx - s * 0.08, cy - s * 0.32)
    ear.lineTo(cx - s * 0.02, cy - s * 0.14)
    ear.lineTo(cx + s * 0.02, cy - s * 0.14)
    ear.lineTo(cx + s * 0.08, cy - s * 0.32)
    ear.lineTo(cx + s * 0.12, cy - s * 0.12)
    p.fillPath(ear, _color(color, alpha))


def crescent(p, cx, cy, r, color, alpha=255):
    full = QPainterPath()
    full.addEllipse(QPointF(cx, cy), r, r)
    cut = QPainterPath()
    cut.addEllipse(QPointF(cx + r * 0.45, cy - r * 0.2), r * 0.92, r * 0.92)
    p.fillPath(full.subtracted(cut), _color(color, alpha))


def drips(p, rect, color, alpha=200, seed=1, depth=40, count=None):
    """Paint dripping from the top edge (WOD purple drank, gothic blood)."""
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


def cobweb(p, cx, cy, r, color, alpha, start_deg=0, span_deg=90):
    pen = QPen(_color(color, alpha), 1)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    spokes = 6
    pts = []
    for i in range(spokes + 1):
        ang = math.radians(start_deg + span_deg * i / spokes)
        pts.append((math.cos(ang), math.sin(ang)))
        p.drawLine(QPointF(cx, cy), QPointF(cx + math.cos(ang) * r, cy + math.sin(ang) * r))
    for ring in (0.3, 0.52, 0.74, 0.95):
        path = QPainterPath()
        for i, (dx, dy) in enumerate(pts):
            pt = QPointF(cx + dx * r * ring, cy + dy * r * ring)
            if i == 0:
                path.moveTo(pt)
            else:
                prev = pts[i - 1]
                mid = QPointF(cx + (dx + prev[0]) / 2 * r * ring * 0.86, cy + (dy + prev[1]) / 2 * r * ring * 0.86)
                path.quadTo(mid, pt)
        p.drawPath(path)


def candle(p, x, bottom, h, color, alpha):
    w = h * 0.22
    body = QRectF(x - w / 2, bottom - h, w, h)
    p.setPen(Qt.NoPen)
    p.setBrush(_color(color, alpha))
    p.drawRoundedRect(body, 2, 2)
    glow = QRadialGradient(QPointF(x, bottom - h - h * 0.18), h * 0.45)
    glow.setColorAt(0, _color("#ffd27a", alpha))
    glow.setColorAt(1, _color("#ff6a00", 0))
    p.setBrush(glow)
    p.drawEllipse(QPointF(x, bottom - h - h * 0.18), h * 0.45, h * 0.45)
    flame = QPainterPath(QPointF(x, bottom - h - h * 0.38))
    flame.quadTo(x + w * 0.5, bottom - h - h * 0.12, x, bottom - h - h * 0.02)
    flame.quadTo(x - w * 0.5, bottom - h - h * 0.12, x, bottom - h - h * 0.38)
    p.fillPath(flame, _color("#ffe2a0", alpha))


def fangs(p, cx, cy, size, alpha):
    """Vampire smile: two fangs under a lip line."""
    pen = QPen(_color(theme.RED, alpha), max(1.5, size * 0.06))
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    path = QPainterPath(QPointF(cx - size / 2, cy))
    path.quadTo(cx, cy + size * 0.18, cx + size / 2, cy)
    p.drawPath(path)
    p.setPen(Qt.NoPen)
    for sx in (-0.2, 0.2):
        fang = QPainterPath(QPointF(cx + size * sx - size * 0.07, cy + size * 0.05))
        fang.lineTo(cx + size * sx, cy + size * 0.35)
        fang.lineTo(cx + size * sx + size * 0.07, cy + size * 0.06)
        fang.closeSubpath()
        p.fillPath(fang, _color("#ffffff", alpha))
    drop = QPainterPath(QPointF(cx + size * 0.2, cy + size * 0.36))
    drop.quadTo(cx + size * 0.26, cy + size * 0.5, cx + size * 0.2, cy + size * 0.55)
    drop.quadTo(cx + size * 0.14, cy + size * 0.5, cx + size * 0.2, cy + size * 0.36)
    p.fillPath(drop, _color(theme.RED, alpha))


def pill(p, cx, cy, length, width, angle, c1, c2, alpha):
    p.save()
    p.translate(cx, cy)
    p.rotate(angle)
    half = length / 2
    shape = QPainterPath()
    shape.addRoundedRect(QRectF(-half, -width / 2, length, width), width / 2, width / 2)
    p.setClipPath(shape)
    p.fillRect(QRectF(-half, -width / 2, half, width), _color(c1, alpha))
    p.fillRect(QRectF(0, -width / 2, half, width), _color(c2, alpha))
    p.setClipping(False)
    p.setPen(QPen(_color("#ffffff", alpha * 0.5), 1))
    p.drawLine(QPointF(-half + width * 0.5, -width * 0.22), QPointF(-width * 0.2, -width * 0.22))
    p.restore()


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


def heart(p, cx, cy, size, color, alpha=255, angle=0.0):
    """A small filled heart."""
    p.save()
    p.translate(cx, cy)
    p.rotate(angle)
    s = size / 2.0
    path = QPainterPath()
    path.moveTo(0, s * 0.9)
    path.cubicTo(-s * 1.3, s * 0.05, -s * 0.95, -s * 1.05, 0, -s * 0.4)
    path.cubicTo(s * 0.95, -s * 1.05, s * 1.3, s * 0.05, 0, s * 0.9)
    p.setPen(Qt.NoPen)
    p.setBrush(_color(color, alpha))
    p.drawPath(path)
    p.restore()


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


_GLYPHS = "ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜ0123456789Z:.=*+-<>|"


def rain_static(p, rect, seed=1, strength=1.0):
    rng = random.Random(seed)
    f = QFont("MS Gothic")
    f.setPixelSize(13)
    p.setFont(f)
    step = 14
    x = rect.left() + 4
    while x < rect.right():
        if rng.random() < 0.55:
            y = rect.top() + rng.uniform(-40, rect.height() * 0.7)
            n = rng.randint(4, 18)
            for i in range(n):
                a = (18 + 50 * (i / n)) if i < n - 1 else 120
                p.setPen(_color("#00ff46", a * strength))
                p.drawText(QPointF(x, y + i * step), rng.choice(_GLYPHS))
        x += step


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
    if kind == "999":
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
    elif kind == "rain":
        rain_static(p, rect, 7, 1.0)
        pill(p, rect.left() + w * 0.35, b - 70, 34, 13, -25, "#ff2a2a", "#ff6b6b", 230)
        pill(p, rect.left() + w * 0.65, b - 62, 34, 13, 25, "#2a6bff", "#6ba0ff", 230)
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
    elif kind == "noir":
        spot = QRadialGradient(QPointF(rect.center().x(), b - rect.height() * 0.3), w * 0.9)
        spot.setColorAt(0, _color("#ffffff", 22))
        spot.setColorAt(1, _color("#ffffff", 0))
        p.fillRect(rect, spot)
        _draw(p, art("gf_hand"), rect.right() - 12, rect.top() + 46, w=w * 0.38, opacity=0.55, anchor="topright")
        _draw(p, art("gf_don"), rect.left() + w * 0.42, b + 6, h=rect.height() * 0.78, opacity=0.8,
              anchor="bottomcenter")
    elif kind == "gothic":
        from .widgets import cat_pixmap
        crescent(p, rect.right() - 36, rect.top() + 30, 18, "#f2f2f2", 200)
        _stars(p, rect, rng, 22, "#ffffff", 170, big=0.45, r=(4, 8))
        for i in range(4):
            bat(p, rng.uniform(rect.left() + 20, rect.right() - 20), rect.top() + 20 + i * 34,
                rng.uniform(22, 34), theme.TEXT if i % 2 else theme.RED, 190, flap=rng.uniform(-0.3, 0.6))
        cat = cat_pixmap(theme.RED)
        _draw(p, cat, rect.left() + 8, b - 120, w=w * 0.62, opacity=0.65, anchor="bottomleft")
        _draw(p, cat_pixmap("#f6f2f4"), rect.right() - 8, b - 40, w=w * 0.42, opacity=0.35, anchor="bottomright")
        candle(p, rect.right() - 30, b - 130, 26, "#f2f2f2", 170)
        for hx, hy, hs, ha in ((0.18, 0.42, 12, -15), (0.78, 0.5, 9, 12), (0.5, 0.3, 7, 0)):
            heart(p, rect.left() + w * hx, rect.top() + rect.height() * hy, hs, theme.RED, 200, ha)
    p.restore()


def paint_backdrop(p, rect):
    """Faint art behind the content pages (song lists, grids, album / artist pages)."""
    kind = theme.DECOR
    rng = random.Random(9)
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    w, h = rect.width(), rect.height()
    if kind == "999":
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
    elif kind == "rain":
        rain_static(p, rect, 3, 0.5)
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
    elif kind == "noir":
        spot = QRadialGradient(QPointF(rect.right() - w * 0.15, rect.top() + h * 0.2), w * 0.55)
        spot.setColorAt(0, _color("#ffffff", 12))
        spot.setColorAt(1, _color("#ffffff", 0))
        p.fillRect(rect, spot)
        _draw(p, art("gf_don"), rect.right() - w * 0.12, rect.bottom() + h * 0.02, h=h * 0.95, opacity=0.1,
              anchor="bottomcenter")
        _draw(p, art("gf_hand"), rect.right() - w * 0.3, rect.top() - 4, w=min(w * 0.16, 240), opacity=0.06,
              anchor="topcenter")
    elif kind == "gothic":
        from .widgets import cat_pixmap
        cx, cy = rect.center().x(), rect.center().y() + h * 0.06
        _draw(p, cat_pixmap(theme.RED), cx, cy + h * 0.06, w=min(w * 0.42, h * 0.75), opacity=0.06, anchor="center")
        crescent(p, rect.right() - w * 0.08, rect.top() + h * 0.12, min(w, h) * 0.05, "#f2f2f2", 22)
        cobweb(p, rect.left(), rect.top(), min(w, h) * 0.22, "#ffffff", 22, 0, 90)
        cobweb(p, rect.right(), rect.top(), min(w, h) * 0.16, "#ffffff", 18, 90, 90)
        for _ in range(7):
            bat(p, rng.uniform(rect.left() + w * 0.55, rect.right() - 30), rng.uniform(rect.top() + 20, rect.top() + h * 0.35),
                rng.uniform(18, 34), theme.TEXT, 24, flap=rng.uniform(-0.3, 0.6))
        _stars(p, rect, rng, 40, "#ffffff", 40, big=0.35, r=(3, 7))
        drips(p, QRectF(rect.left(), rect.top(), w, 22), "#8a0f3c", 70, seed=5, depth=20, count=max(8, int(w / 60)))
        for x in (rect.left() + 28, rect.right() - 28):
            candle(p, x, rect.bottom() - 18, 34, "#f2f2f2", 40)
        for _ in range(6):
            heart(p, rng.uniform(rect.left() + w * 0.3, rect.right() - 30), rng.uniform(rect.top() + 40, rect.bottom() - 40),
                  rng.uniform(10, 20), theme.RED, 34, rng.uniform(-20, 20))
    p.restore()


def paint_panel(p, rect):
    """A small accent in the bottom-right corner (settings pages, mini player)."""
    kind = theme.DECOR
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    r, b = rect.right() - 12, rect.bottom() - 12
    if kind == "999":
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
    elif kind == "rain":
        pill(p, r - 70, b - 14, 30, 12, -20, "#ff2a2a", "#ff6b6b", 120)
        pill(p, r - 25, b - 14, 30, 12, 20, "#2a6bff", "#6ba0ff", 120)
    elif kind == "tpne":
        murakami_flower(p, r - 40, b - 40, 40, 170, 0)
        murakami_flower(p, r - 112, b - 22, 22, 140, 5, 15)
        _draw(p, art("tpne_planet"), r - 150, b - 70, w=120, opacity=0.35, anchor="bottomright")
    elif kind == "lnd":
        meteor(p, r - 120, b - 120, 70, 64, 120)
        butterfly(p, r - 30, b - 40, 34, 18, 170)
        butterfly(p, r - 90, b - 80, 22, -20, 130, flap=0.3)
        feather(p, r - 150, b - 30, 22, 40, 110)
    elif kind == "noir":
        _draw(p, art("gf_rose"), r, b, w=34, opacity=0.6, anchor="bottomright")
        _draw(p, art("gf_hand"), r - 46, b - 10, w=110, opacity=0.25, anchor="bottomright")
    elif kind == "gothic":
        from .widgets import cat_pixmap
        _draw(p, cat_pixmap(theme.RED), r, b, w=120, opacity=0.3, anchor="bottomright")
        bat(p, r - 150, b - 70, 28, theme.TEXT, 70, 0.3)
        bat(p, r - 110, b - 100, 20, theme.RED, 90, -0.2)
        sparkle(p, r - 30, b - 110, 7, "#ffffff", 120)
        fangs(p, r - 175, b - 20, 30, 110)
    p.restore()


def card_art(p, name, rect):
    """Little picture for a theme's card in the settings."""
    decor = theme.THEMES.get(name, {}).get("DECOR")
    from .widgets import cat_pixmap
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    r, b = rect.right() - 6, rect.bottom() - 6
    if name == "999":
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
    elif name == "matrix":
        pill(p, r - 34, b - 46, 20, 8, -25, "#ff2a2a", "#ff6b6b", 230)
        pill(p, r - 12, b - 46, 20, 8, 25, "#2a6bff", "#6ba0ff", 230)
    elif name == "tpne":
        murakami_flower(p, r - 18, b - 44, 18, 255, 0)
        murakami_flower(p, r - 48, b - 38, 11, 240, 4, 20)
    elif name == "lnd":
        meteor(p, r - 40, b - 64, 34, 64, 200)
        butterfly(p, r - 14, b - 42, 22, 15, 240)
        butterfly(p, r - 44, b - 36, 14, -20, 220, flap=0.3)
    elif decor == "noir":
        _draw(p, art("gf_rose"), r, b - 30, w=18, opacity=0.95, anchor="bottomright")
        _draw(p, art("gf_hand"), r - 24, b - 34, w=44, opacity=0.9, anchor="bottomright")
    elif decor == "gothic":
        _draw(p, cat_pixmap("#ff4fa3"), r, b - 30, w=58, opacity=0.95, anchor="bottomright")
        bat(p, r - 70, b - 70, 16, "#ffffff", 200, 0.3)


def paint_lyrics(p, rect):
    """Light touches over the lyrics backdrop."""
    kind = theme.DECOR
    rng = random.Random(4)
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    if kind == "wod":
        drips(p, QRectF(rect.left(), rect.top(), rect.width(), 26), theme.RED_DARK, 110, seed=8, depth=24,
              count=max(8, int(rect.width() / 70)))
    elif kind == "gothic":
        _stars(p, rect, rng, 26, "#ffffff", 50, big=0.4)
        drips(p, QRectF(rect.left(), rect.top(), rect.width(), 22), "#8a0f3c", 120, seed=5, depth=20,
              count=max(8, int(rect.width() / 60)))
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
    elif kind == "noir":
        spot = QRadialGradient(QPointF(rect.center().x(), rect.top() - 40), rect.width() * 0.6)
        spot.setColorAt(0, _color("#ffffff", 26))
        spot.setColorAt(1, _color("#ffffff", 0))
        p.fillRect(rect, spot)
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


class MatrixRain(QWidget):
    """Animated code rain. Each column is a pre-rendered strip that is only moved,
    so a frame costs ~one drawPixmap per column (cheap even at full screen)."""

    def __init__(self, parent=None, density=0.75, fps=30):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._density = density
        self._cols = []
        self._strips = []
        self._timer = QTimer(self)
        self._timer.setInterval(int(1000 / fps))
        self._timer.timeout.connect(self._step)
        self._rng = random.Random(9)
        self._font = QFont("MS Gothic")
        self._font.setPixelSize(16)
        self._cell = QFontMetricsF(self._font).height()
        self._build_strips()

    def _build_strips(self):
        self._strips = []
        cell = self._cell
        for _ in range(12):
            n = self._rng.randint(8, 26)
            pm = QPixmap(int(cell), int(cell * n))
            pm.fill(Qt.transparent)
            q = QPainter(pm)
            q.setFont(self._font)
            for i in range(n):
                level = (i + 1) / n
                c = QColor("#00ff46") if i < n - 1 else QColor("#d8ffe0")
                c.setAlpha(int(25 + 170 * level ** 1.6) if i < n - 1 else 255)
                q.setPen(c)
                q.drawText(QRectF(0, i * cell, cell, cell), Qt.AlignCenter, self._rng.choice(_GLYPHS))
            q.end()
            self._strips.append(pm)

    def _layout(self):
        cell = self._cell
        n = int(self.width() / cell) + 1
        self._cols = []
        for i in range(n):
            if self._rng.random() > self._density:
                continue
            strip = self._rng.randrange(len(self._strips))
            self._cols.append([i * cell, self._rng.uniform(-self.height(), self.height()),
                               self._rng.uniform(1.6, 5.0), strip])

    def resizeEvent(self, event):
        self._layout()
        super().resizeEvent(event)

    def showEvent(self, event):
        self._timer.start()

    def hideEvent(self, event):
        self._timer.stop()

    def _step(self):
        h = self.height()
        for col in self._cols:
            col[1] += col[2]
            if col[1] > h:
                col[1] = -self._strips[col[3]].height() - self._rng.uniform(0, h * 0.5)
                col[3] = self._rng.randrange(len(self._strips))
                col[2] = self._rng.uniform(1.6, 5.0)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setOpacity(0.55)
        for x, y, _, strip in self._cols:
            p.drawPixmap(QPointF(x, y), self._strips[strip])


class GothicNight(QWidget):
    """The gothic theme behind the synced lyrics: a glowing moon, drifting clouds, bats flying past and hearts
    floating up - and on some songs a light rain. Everything is faint and slow so the text stays first."""

    def __init__(self, parent=None, fps=24):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._rng = random.Random()
        self._t = 0.0
        self._dt = 1.0 / fps
        self._timer = QTimer(self)
        self._timer.setInterval(int(1000 / fps))
        self._timer.timeout.connect(self._step)
        self.raining = False
        self.cover_side = "left"
        self._moon = None
        self._clouds = []
        self._bats = []
        self._hearts = []
        self._drops = []

    # ------------------------------------------------------------------ setup
    def reroll(self):
        """New song: rain or a clear sky, chosen at random."""
        self.raining = self._rng.random() < 0.5
        self._drops = self._make_drops() if self.raining else []

    def _make_moon(self):
        r = max(18.0, min(self.width(), self.height()) * 0.032)
        side = int(r * 6)
        pm = QPixmap(side, side)
        pm.fill(Qt.transparent)
        q = QPainter(pm)
        q.setRenderHint(QPainter.Antialiasing)
        c = QPointF(side / 2, side / 2)
        glow = QRadialGradient(c, side / 2)
        glow.setColorAt(0, _color("#ffd6ea", 70))
        glow.setColorAt(0.35, _color(theme.RED, 22))
        glow.setColorAt(1, _color(theme.RED, 0))
        q.setPen(Qt.NoPen)
        q.setBrush(glow)
        q.drawEllipse(c, side / 2, side / 2)
        crescent(q, c.x(), c.y(), r, "#f6eef2", 210)
        q.end()
        return pm

    def _make_cloud(self, w):
        h = w * 0.36
        pm = QPixmap(int(w), int(h))
        pm.fill(Qt.transparent)
        q = QPainter(pm)
        q.setRenderHint(QPainter.Antialiasing)
        q.setPen(Qt.NoPen)
        for _ in range(7):
            cx = self._rng.uniform(w * 0.2, w * 0.8)
            cy = self._rng.uniform(h * 0.45, h * 0.65)
            rr = self._rng.uniform(h * 0.25, h * 0.45)
            g = QRadialGradient(QPointF(cx, cy), rr)
            g.setColorAt(0, _color("#d9c8d2", 20))
            g.setColorAt(1, _color("#d9c8d2", 0))
            q.setBrush(g)
            q.drawEllipse(QPointF(cx, cy), rr, rr)
        q.end()
        return pm

    def _make_drops(self):
        w, h = max(1, self.width()), max(1, self.height())
        n = int(w * h / 9000)
        return [[self._rng.uniform(-w * 0.1, w), self._rng.uniform(0, h), self._rng.uniform(9, 16),
                 self._rng.uniform(10, 22)] for _ in range(n)]

    def _new_bat(self, first=False):
        w, h = self.width(), self.height()
        going_right = self._rng.random() < 0.5
        return {"x": self._rng.uniform(0, w) if first else (-40 if going_right else w + 40),
                "y": self._rng.uniform(h * 0.05, h * 0.3), "dir": 1 if going_right else -1,
                "speed": self._rng.uniform(40, 70), "size": self._rng.uniform(18, 30),
                "phase": self._rng.uniform(0, 6.28), "wait": 0.0 if first else self._rng.uniform(2, 9)}

    def _new_heart(self, first=False):
        w, h = self.width(), self.height()
        return {"x": self._rng.uniform(w * 0.05, w * 0.95), "y": self._rng.uniform(h * 0.3, h) if first else h + 20,
                "speed": self._rng.uniform(14, 26), "size": self._rng.uniform(9, 16),
                "phase": self._rng.uniform(0, 6.28), "alpha": self._rng.uniform(40, 80)}

    def _layout(self):
        w, h = self.width(), self.height()
        if w < 10 or h < 10:
            return
        self._moon = self._make_moon()
        self._clouds = []
        for i in range(4):
            cw = self._rng.uniform(w * 0.22, w * 0.38)
            self._clouds.append([self._rng.uniform(-cw, w), self._rng.uniform(-cw * 0.2, h * 0.06),
                                 self._rng.uniform(5, 11), self._make_cloud(cw)])
        self._bats = [self._new_bat(first=True) for _ in range(3)]
        self._hearts = [self._new_heart(first=True) for _ in range(7)]
        if self.raining:
            self._drops = self._make_drops()

    def resizeEvent(self, event):
        self._layout()
        super().resizeEvent(event)

    def showEvent(self, event):
        if self._moon is None:
            self._layout()
        self._timer.start()

    def hideEvent(self, event):
        self._timer.stop()

    # ------------------------------------------------------------------ animation
    def _step(self):
        dt = self._dt
        self._t += dt
        w, h = self.width(), self.height()
        for c in self._clouds:
            c[0] += c[2] * dt
            if c[0] > w:
                c[0] = -c[3].width()
        for b in self._bats:
            if b["wait"] > 0:
                b["wait"] -= dt
                continue
            b["x"] += b["dir"] * b["speed"] * dt
            if b["x"] < -60 or b["x"] > w + 60:
                b.update(self._new_bat())
        for i, hh in enumerate(self._hearts):
            hh["y"] -= hh["speed"] * dt
            if hh["y"] < h * 0.15:
                self._hearts[i] = self._new_heart()
        for d in self._drops:
            d[0] += d[2] * 0.3 * dt * 30
            d[1] += d[2] * dt * 30
            if d[1] > h:
                d[0], d[1] = self._rng.uniform(-w * 0.1, w), -d[3]
        self.update()

    def paintEvent(self, event):
        if self._moon is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        # the moon breathes a little
        p.setOpacity(0.42 + 0.06 * math.sin(self._t * 0.6))
        m = self._moon
        # above the cover, away from the text and the toolbar
        cx = w * (0.25 if self.cover_side == "left" else 0.72)
        p.drawPixmap(QPointF(cx - m.width() / 2, max(4.0, h * 0.045) - m.height() / 2), m)
        p.setOpacity(0.7 if self.raining else 0.45)
        for x, y, _, pm in self._clouds:
            p.drawPixmap(QPointF(x, y), pm)
        p.setOpacity(1.0)
        if self._drops:
            p.setPen(QPen(_color("#e6d6e0", 38), 1.1, Qt.SolidLine, Qt.RoundCap))
            p.drawLines([QLineF(x, y, x + ln * 0.3, y + ln) for x, y, _, ln in self._drops])
        for b in self._bats:
            if b["wait"] > 0:
                continue
            flap = math.sin(self._t * 9 + b["phase"]) * 0.6
            y = b["y"] + math.sin(self._t * 1.5 + b["phase"]) * 12
            bat(p, b["x"], y, b["size"], "#f6f2f4", 55, flap=flap)
        for hh in self._hearts:
            fade = max(0.0, min(1.0, (hh["y"] - h * 0.15) / (h * 0.25)))
            x = hh["x"] + math.sin(self._t * 0.9 + hh["phase"]) * 14
            heart(p, x, hh["y"], hh["size"], theme.RED, hh["alpha"] * fade, math.sin(self._t + hh["phase"]) * 12)


def lyrics_background(p, rect):
    """Backdrop for the lyrics view when there is no cover (theme gradient)."""
    grad = QLinearGradient(0, 0, rect.width(), rect.height())
    grad.setColorAt(0, QColor(theme.LYR_BG[0]))
    grad.setColorAt(0.55, QColor(theme.LYR_BG[1]))
    grad.setColorAt(1, QColor(theme.LYR_BG[2]))
    p.fillRect(rect, grad)
