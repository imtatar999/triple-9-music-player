"""Synced lyrics renderer.

Spotify-like look by default: left aligned, big bold text, sung lines dimmed,
the current line bright, upcoming lines in a softer tint. Scrolling is eased
at display refresh rate; only visible rows are painted.
"""

import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget

from .. import theme
from ..lyrics import INSTRUMENTAL


def _mix(a, b, t):
    t = min(1.0, max(0.0, t))
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
        int(a.alpha() + (b.alpha() - a.alpha()) * t),
    )


class _Row:
    __slots__ = ("start", "end", "text", "width", "y")

    def __init__(self, start, end, text, width, y):
        self.start, self.end, self.text, self.width, self.y = start, end, text, width, y


class _LineLayout:
    __slots__ = ("top", "height", "rows", "spans")

    def __init__(self):
        self.top = 0.0
        self.height = 0.0
        self.rows = []
        self.spans = []     # (char_start, char_end, time) per timed word


class LyricsView(QWidget):
    seek_requested = Signal(float)

    def __init__(self, parent=None, size_factor=1.0, compact=False):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)
        self._size_factor = size_factor
        self._compact = compact
        self._lyrics = None
        self._layouts = []
        self._content_h = 0.0
        self._layout_width = -1
        self._position_fn = lambda: 0.0
        self._playing_fn = lambda: False
        self._offset = 0.0
        self._scroll = 0.0
        self._target = 0.0
        self._active = -1
        self._prev_active = -1
        self._active_since = 0.0
        self._user_scroll_until = 0.0
        self._hover_line = -1
        self._last_tick = time.perf_counter()
        self._message = (theme.say("No lyrics"), "")
        # style
        self._family = theme.FONT
        self._base_size = 30
        self._bold = True
        self._align = "left"
        self._c_active = QColor("#ffffff")
        self._c_upcoming = QColor("#d9a3a8")
        self._c_past = QColor("#6e4a4f")
        self._karaoke = True
        self._font = QFont()
        self._fm = None
        self._rebuild_font()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    # ------------------------------------------------------------------ config
    def set_sources(self, position_fn, playing_fn):
        self._position_fn = position_fn
        self._playing_fn = playing_fn

    def set_offset(self, seconds):
        self._offset = float(seconds or 0.0)

    def set_style(self, family=None, size=None, bold=None, align=None, active=None,
                  upcoming=None, past=None, karaoke=None):
        if family is not None:
            self._family = family
        if size is not None:
            self._base_size = int(size)
        if bold is not None:
            self._bold = bool(bold)
        if align is not None:
            self._align = align
        if active is not None:
            self._c_active = QColor(active)
        if upcoming is not None:
            self._c_upcoming = QColor(upcoming)
        if past is not None:
            self._c_past = QColor(past)
        if karaoke is not None:
            self._karaoke = bool(karaoke)
        self._rebuild_font()
        self._layout_width = -1
        self._ensure_layout()
        self._snap()
        self.update()

    def set_size_factor(self, factor):
        if abs(factor - self._size_factor) > 1e-3:
            self._size_factor = factor
            self._rebuild_font()
            self._layout_width = -1
            self._ensure_layout()
            self._snap()
            self.update()

    def _rebuild_font(self):
        f = QFont(self._family)
        f.setPixelSize(max(9, int(round(self._base_size * self._size_factor))))
        f.setWeight(QFont.Bold if self._bold else QFont.Medium)
        f.setLetterSpacing(QFont.PercentageSpacing, 98 if self._bold else 100)
        f.setHintingPreference(QFont.PreferNoHinting)
        self._font = f
        self._fm = QFontMetricsF(f)

    def set_lyrics(self, lyrics, message=None):
        """lyrics: Lyrics or None. message: (title, hint) shown when None."""
        self._lyrics = lyrics if lyrics and not lyrics.is_empty() else None
        if message:
            self._message = message
        self._active = -1
        self._prev_active = -1
        self._hover_line = -1
        self._user_scroll_until = 0.0
        self._layout_width = -1
        self._ensure_layout()
        self._snap()
        self.update()

    @property
    def lyrics(self):
        return self._lyrics

    # ------------------------------------------------------------------ layout
    def _margins(self):
        side = 28 if self._compact else 56
        return side * min(1.0, max(0.5, self.width() / 900)) + (12 if self._compact else 0)

    def _ensure_layout(self):
        if self._lyrics is None or self._fm is None:
            self._layouts = []
            self._content_h = 0.0
            return
        width = self.width()
        if width == self._layout_width:
            return
        self._layout_width = width
        margin = self._margins()
        avail = max(60.0, width - 2 * margin)
        fm = self._fm
        line_h = fm.height() * 1.08
        gap = fm.height() * (0.42 if not self._compact else 0.35)
        y = 0.0
        layouts = []
        for line in self._lyrics.lines:
            lay = _LineLayout()
            lay.top = y
            text = line.text
            lay.rows = self._wrap(text, avail, fm)
            for i, row in enumerate(lay.rows):
                row.y = i * line_h
            lay.height = max(1, len(lay.rows)) * line_h
            if line.words:
                pos = 0
                for w in line.words:
                    lay.spans.append((pos, pos + len(w.text), w.time))
                    pos += len(w.text)
            layouts.append(lay)
            y += lay.height + gap
        self._layouts = layouts
        self._content_h = max(0.0, y - gap)

    @staticmethod
    def _wrap(text, avail, fm):
        if not text:
            return [_Row(0, 0, "", 0.0, 0.0)]
        rows = []
        n = len(text)
        start = 0
        while start < n:
            while start < n and text[start] == " ":
                start += 1
            if start >= n:
                break
            if fm.horizontalAdvance(text[start:]) <= avail:
                end = n
            else:
                end = start
                last_fit = -1
                i = start
                while i <= n:
                    if i == n or text[i] == " ":
                        if fm.horizontalAdvance(text[start:i]) <= avail:
                            last_fit = i
                        else:
                            break
                    i += 1
                if last_fit <= start:
                    # one very long word: break by characters
                    end = start + 1
                    while end < n and fm.horizontalAdvance(text[start:end + 1]) <= avail:
                        end += 1
                else:
                    end = last_fit
            chunk = text[start:end].rstrip()
            rows.append(_Row(start, start + len(chunk), chunk, fm.horizontalAdvance(chunk), 0.0))
            start = end
        return rows or [_Row(0, 0, "", 0.0, 0.0)]

    def _anchor(self):
        return self.height() * (0.30 if not self._compact else 0.28)

    def _target_for(self, index):
        if not self._layouts:
            return 0.0
        if self._lyrics is None or not self._lyrics.synced:
            return self._scroll
        index = max(0, index)
        lay = self._layouts[min(index, len(self._layouts) - 1)]
        return lay.top + lay.height / 2 - self._anchor()

    def _clamp_scroll(self, value):
        lo = -self.height() * 0.5
        hi = max(lo, self._content_h - self.height() * 0.5)
        return min(max(value, lo), hi)

    def _snap(self):
        if self._lyrics is not None and self._lyrics.synced:
            idx = self._lyrics.index_at(self._time())
            self._active = idx
            self._target = self._target_for(idx)
        else:
            self._target = -self._top_padding()
        self._scroll = self._target

    def _top_padding(self):
        return 24 if self._compact else 48

    def _time(self):
        try:
            return self._position_fn() + self._offset
        except Exception:
            return 0.0

    # ------------------------------------------------------------------ animation
    def showEvent(self, event):
        self._ensure_layout()
        self._snap()
        self._last_tick = time.perf_counter()
        self._timer.start()

    def hideEvent(self, event):
        self._timer.stop()

    def resizeEvent(self, event):
        self._ensure_layout()
        if time.perf_counter() > self._user_scroll_until:
            self._snap()

    def _tick(self):
        now = time.perf_counter()
        dt = min(0.1, now - self._last_tick)
        self._last_tick = now
        lyr = self._lyrics
        if lyr is None:
            return
        changed = False
        if lyr.synced:
            idx = lyr.index_at(self._time())
            if idx != self._active:
                self._prev_active = self._active
                self._active = idx
                self._active_since = now
                changed = True
            if now >= self._user_scroll_until:
                self._target = self._target_for(self._active)
        diff = self._target - self._scroll
        if abs(diff) > 0.3:
            # critically damped ease: fast start, soft landing
            self._scroll += diff * (1.0 - math.exp(-dt * 9.0))
            changed = True
        elif diff:
            self._scroll = self._target
            changed = True
        fading = now - self._active_since < 0.4
        karaoke = self._karaoke and lyr.synced and 0 <= self._active < len(lyr.lines) and lyr.lines[self._active].words
        if changed or fading or (karaoke and self._playing_fn()):
            self.update()

    # ------------------------------------------------------------------ input
    def wheelEvent(self, event):
        if self._lyrics is None:
            return
        delta = event.angleDelta().y()
        self._target = self._clamp_scroll(self._target - delta * 0.9)
        self._user_scroll_until = time.perf_counter() + 3.5
        if not self._timer.isActive():
            self._scroll = self._target
            self.update()

    def _line_at(self, y):
        doc_y = y + self._scroll
        for i, lay in enumerate(self._layouts):
            if lay.top - 6 <= doc_y <= lay.top + lay.height + 6:
                return i
        return -1

    def mouseMoveEvent(self, event):
        synced = self._lyrics is not None and self._lyrics.synced
        line = self._line_at(event.position().y()) if synced else -1
        if line != self._hover_line:
            self._hover_line = line
            self.setCursor(Qt.PointingHandCursor if line >= 0 else Qt.ArrowCursor)
            self.update()

    def leaveEvent(self, event):
        if self._hover_line != -1:
            self._hover_line = -1
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton or self._lyrics is None or not self._lyrics.synced:
            return
        line = self._line_at(event.position().y())
        if line >= 0:
            t = self._lyrics.lines[line].time - self._offset
            self._user_scroll_until = 0.0
            self.seek_requested.emit(max(0.0, t))

    # ------------------------------------------------------------------ painting
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        if self._lyrics is None:
            self._paint_message(p)
            return
        self._ensure_layout()
        p.setFont(self._font)
        fm = self._fm
        margin = self._margins()
        avail = max(60.0, self.width() - 2 * margin)
        h = self.height()
        fade_zone = min(110.0, h * 0.16)
        now = time.perf_counter()
        fade_t = min(1.0, (now - self._active_since) / 0.28)
        synced = self._lyrics.synced
        t_now = self._time() if synced else 0.0
        ascent = fm.ascent()
        lines = self._lyrics.lines
        for i, lay in enumerate(self._layouts):
            top = lay.top - self._scroll
            if top > h:
                break
            if top + lay.height < 0:
                continue
            color = self._line_color(i, synced, fade_t)
            if i == self._hover_line and i != self._active:
                color = _mix(color, self._c_active, 0.45)
            karaoke = (synced and self._karaoke and i == self._active and lay.spans and fade_t >= 0)
            for row in lay.rows:
                y = top + row.y
                if y > h or y + fm.height() < 0:
                    continue
                center = y + fm.height() / 2
                alpha = 1.0
                if center < fade_zone:
                    alpha = max(0.0, center / fade_zone)
                elif center > h - fade_zone:
                    alpha = max(0.0, (h - center) / fade_zone)
                if alpha <= 0.01:
                    continue
                x = margin if self._align == "left" else margin + (avail - row.width) / 2
                p.setOpacity(alpha)
                if karaoke:
                    self._paint_karaoke_row(p, lines[i], lay, row, x, y + ascent, t_now)
                else:
                    p.setPen(color)
                    p.drawText(QPointF(x, y + ascent), row.text)
        p.setOpacity(1.0)

    def _line_color(self, i, synced, fade_t):
        if not synced:
            return self._c_upcoming if self._lyrics.lines[i].text != INSTRUMENTAL else self._c_past
        if i == self._active:
            return _mix(self._c_upcoming, self._c_active, fade_t)
        if i < self._active:
            if i == self._prev_active:
                return _mix(self._c_active, self._c_past, fade_t)
            return self._c_past
        return self._c_upcoming

    def _paint_karaoke_row(self, p, line, lay, row, x, baseline, t):
        """Base colour for the whole row, then the sung part clipped in the active colour."""
        progressed = 0.0
        for k, (c0, c1, wt) in enumerate(lay.spans):
            if t < wt:
                break
            nxt = lay.spans[k + 1][2] if k + 1 < len(lay.spans) else max(line.end, wt + 0.4)
            dur = max(0.05, min(nxt - wt, 1.6))
            frac = min(1.0, (t - wt) / dur)
            progressed = c0 + (c1 - c0) * frac
        fm = self._fm
        sung_color = self._c_active
        rest_color = _mix(self._c_upcoming, self._c_active, 0.25)
        p.setPen(rest_color)
        p.drawText(QPointF(x, baseline), row.text)
        if progressed <= row.start:
            return
        upto = min(progressed, row.start + len(row.text))
        whole = int(upto)
        part = upto - whole
        px = fm.horizontalAdvance(row.text[: max(0, whole - row.start)])
        if part > 0 and whole - row.start < len(row.text):
            px += fm.horizontalAdvance(row.text[whole - row.start]) * part
        p.save()
        p.setClipRect(QRectF(x - 2, baseline - fm.ascent() - 4, px + 2, fm.height() + 8))
        p.setPen(sung_color)
        p.drawText(QPointF(x, baseline), row.text)
        p.restore()

    def _paint_message(self, p):
        title, hint = self._message
        rect = QRectF(self.rect()).adjusted(30, 0, -30, 0)
        f = QFont(self._family)
        f.setPixelSize(max(14, int(22 * self._size_factor)))
        f.setWeight(QFont.Bold)
        p.setFont(f)
        p.setPen(QColor(theme.DIM))
        fm = QFontMetricsF(f)
        y = rect.center().y() - fm.height()
        p.drawText(QRectF(rect.left(), y, rect.width(), fm.height() * 1.2), Qt.AlignCenter, title)
        if hint:
            f2 = QFont(theme.FONT)
            f2.setPixelSize(max(11, int(13 * min(1.0, self._size_factor + 0.2))))
            p.setFont(f2)
            p.setPen(QColor(theme.FAINT))
            p.drawText(QRectF(rect.left(), y + fm.height() * 1.4, rect.width(), 80),
                       Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap, hint)
