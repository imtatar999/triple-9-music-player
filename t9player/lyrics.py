"""Lyrics model and LRC / enhanced-LRC parsing.

Supported:
  [mm:ss], [mm:ss.x], [mm:ss.xx], [mm:ss.xxx], [mm:ss:xx], [h:mm:ss.xx]
  several timestamps on one line   [00:12.00][01:30.00]chorus
  word timing (enhanced LRC)        [00:12.00]<00:12.00>Hey <00:12.40>hey
  [offset:+250] header (milliseconds, positive = lyrics earlier)
"""

import bisect
import re
from dataclasses import dataclass, field

_TIME = r"(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?"
_LINE_TS = re.compile(r"\[" + _TIME + r"\]")
# [h:mm:ss.xx] - needs the '.' so that [mm:ss:xx] stays minutes/seconds/hundredths
_HOUR_TS = re.compile(r"\[(\d{1,2}):(\d{2}):(\d{2})\.(\d{1,3})\]")
_WORD_TS = re.compile(r"<" + _TIME + r">")
_TAG = re.compile(r"^\[([a-zA-Z#]+):(.*)\]\s*$")
_ANY_TS = re.compile(r"\[\d{1,3}:\d{1,2}(?:[.:]\d{1,3})?\]")

INSTRUMENTAL = "♪"


@dataclass
class Word:
    time: float
    text: str


@dataclass
class Line:
    time: float          # seconds; -1 for unsynced lyrics
    text: str
    words: list = field(default_factory=list)   # list[Word], may be empty
    end: float = -1.0    # start of next line (filled by finalize)


@dataclass
class Lyrics:
    lines: list
    synced: bool
    source: str = ""     # human readable: "Sidecar .lrc", "Embedded (SYLT)" ...
    path: str = ""       # file the lyrics came from, if any
    _times: list = field(default_factory=list, repr=False)

    def finalize(self):
        if self.synced:
            self.lines.sort(key=lambda ln: ln.time)
            for i, line in enumerate(self.lines):
                nxt = self.lines[i + 1].time if i + 1 < len(self.lines) else line.time + 6.0
                line.end = max(nxt, line.time)
            self._times = [ln.time for ln in self.lines]
        return self

    def index_at(self, position):
        """Index of the line being sung at `position` seconds, -1 before the first."""
        if not self.synced or not self._times:
            return -1
        return bisect.bisect_right(self._times, position) - 1

    @property
    def has_words(self):
        return any(ln.words for ln in self.lines)

    def is_empty(self):
        return not any(ln.text.strip() for ln in self.lines)


def _ts_seconds(mm, ss, frac):
    value = int(mm) * 60 + int(ss)
    if frac:
        value += int(frac) / (10 ** len(frac))
    return float(value)


def looks_synced(text):
    return bool(text) and len(_ANY_TS.findall(text[:4000])) >= 2


def _parse_words(body):
    """Split '<t>word <t>word' into (plain_text, [Word]). Empty list if no word tags."""
    if "<" not in body or not _WORD_TS.search(body):
        return body.strip(), []
    words = []
    pieces = _WORD_TS.split(body)
    # split -> [prefix, mm, ss, frac, text, mm, ss, frac, text, ...]
    prefix = pieces[0]
    if prefix.strip():
        words.append(Word(-1.0, prefix))
    for i in range(1, len(pieces) - 3, 4):
        t = _ts_seconds(pieces[i], pieces[i + 1], pieces[i + 2])
        text = pieces[i + 3]
        if text == "":
            continue
        words.append(Word(t, text))
    if words and words[0].time < 0:
        # leading untimed text inherits the first real timestamp
        first = next((w.time for w in words if w.time >= 0), 0.0)
        words[0].time = first
    plain = "".join(w.text for w in words)
    # normalise whitespace but keep word boundaries
    lead = len(plain) - len(plain.lstrip())
    if lead and words:
        words[0].text = words[0].text.lstrip()
    if words:
        words[-1].text = words[-1].text.rstrip()
    words = [w for w in words if w.text]
    return "".join(w.text for w in words), words


def parse_lrc(text, source="", path=""):
    """Parse LRC text. Returns Lyrics (synced if any timestamps were found)."""
    offset = 0.0
    lines = []
    plain = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        raw = raw.strip("﻿").rstrip()
        if not raw.strip():
            continue
        tag = _TAG.match(raw.strip())
        if tag and not _ANY_TS.match(raw.strip()):
            name = tag.group(1).lower()
            if name == "offset":
                try:
                    offset = int(tag.group(2).strip()) / 1000.0
                except ValueError:
                    pass
            continue
        stamps = []
        rest = raw.strip()
        while True:
            m = _HOUR_TS.match(rest)
            if m:
                h, mm, ss, frac = m.groups()
                stamps.append(int(h) * 3600 + _ts_seconds(mm, ss, frac))
                rest = rest[m.end():]
                continue
            m = _LINE_TS.match(rest)
            if m:
                stamps.append(_ts_seconds(*m.groups()))
                rest = rest[m.end():]
                continue
            break
        if not stamps:
            plain.append(raw.strip())
            continue
        body, words = _parse_words(rest)
        body = body.strip()
        for t in stamps:
            line_words = [Word(max(0.0, w.time - offset), w.text) for w in words] if len(stamps) == 1 else []
            lines.append(Line(max(0.0, t - offset), body if body else "", line_words))
    if lines:
        # collapse runs of empty timed lines into one instrumental marker
        cleaned = []
        lines.sort(key=lambda ln: ln.time)
        for line in lines:
            if not line.text:
                if cleaned and not cleaned[-1].text.strip(INSTRUMENTAL):
                    continue
                if not cleaned:
                    continue  # silence before the first line needs no marker
                line.text = INSTRUMENTAL
            cleaned.append(line)
        # a trailing instrumental marker is noise
        while cleaned and cleaned[-1].text == INSTRUMENTAL:
            cleaned.pop()
        return Lyrics(cleaned, True, source, path).finalize()
    return Lyrics([Line(-1.0, ln) for ln in plain], False, source, path)


def plain_lyrics(text, source="", path=""):
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    # trim blank lines at the ends, keep inner stanza breaks
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return Lyrics([Line(-1.0, ln.strip()) for ln in lines], False, source, path)


def from_sylt(entries, source="Embedded (SYLT)"):
    """entries: iterable of (text, milliseconds)."""
    lines = []
    for text, ms in entries:
        text = (text or "").strip()
        if text:
            lines.append(Line(max(0.0, ms / 1000.0), text))
    if not lines:
        return None
    return Lyrics(lines, True, source).finalize()


def parse_any(text, source="", path=""):
    if not text or not text.strip():
        return None
    lyr = parse_lrc(text, source, path) if looks_synced(text) else plain_lyrics(text, source, path)
    return None if lyr.is_empty() else lyr


def decode_text_file(data):
    """Decode bytes from a lyrics file, trying the encodings people actually use."""
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError:
            pass
    for enc in ("utf-8-sig", "cp1250", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")
