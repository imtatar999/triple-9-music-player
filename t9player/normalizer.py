"""Volume normalization in the background: measures songs (current and next first, then the whole
library, gently) and works out the gain for each one."""

import collections
import logging
import queue
import threading
import time

from . import loudness

_log = logging.getLogger(__name__)

MODES = ("off", "track", "album")


def _album_key(t):
    return ((t.albumartist or t.artist or "").casefold(), (t.album or "").casefold())


class Normalizer:
    def __init__(self, library):
        self.library = library
        self.mode = "off"
        self._known = None                 # path -> (mtime, size, lufs, peak)
        self._urgent = collections.deque()
        self._background = collections.deque()
        self._queued = set()
        self._done = queue.SimpleQueue()   # paths measured since the last finished() call
        self._wake = threading.Event()
        self._cancel = threading.Event()
        self._thread = None
        self._albums = None                # album key -> loudness (cache, album mode)

    # ------------------------------------------------------------------ control
    def set_mode(self, mode, tracks=()):
        self.mode = mode if mode in MODES else "off"
        self._albums = None
        if self.mode == "off":
            self._background.clear()
            return
        self._load_known()
        for t in tracks:
            if t.path not in self._queued and self._lookup(t.path) is None:
                self._queued.add(t.path)
                self._background.append(t.path)
        self._start()

    def prioritize(self, paths):
        if self.mode == "off":
            return
        self._load_known()
        for p in reversed([p for p in paths if p]):
            if self._lookup(p) is None:
                self._urgent.appendleft(p)
        self._start()
        self._wake.set()

    def stop(self):
        self._cancel.set()
        self._wake.set()

    def finished(self):
        out = []
        while True:
            try:
                out.append(self._done.get_nowait())
            except queue.Empty:
                return out

    def progress(self):
        """(measured, waiting) - for the settings window."""
        known = len(self._known or {})
        return known, len(self._background) + len(self._urgent)

    # ------------------------------------------------------------------ gains
    def gain(self, track):
        """Linear gain for the song, or None while it has not been measured yet."""
        if self.mode == "off" or track is None:
            return 1.0
        hit = self._lookup(track.path)
        if hit is None:
            return None
        lufs, peak = hit
        if self.mode == "album" and track.album:
            album = self._album_loudness(track)
            if album is not None:
                lufs = album
        return loudness.gain_for(lufs, peak)

    def typical_gain(self):
        """A good first guess for a song not measured yet: the median gain of the library."""
        values = sorted(loudness.gain_for(v[2], v[3]) for v in (self._known or {}).values() if v[2] is not None)
        return values[len(values) // 2] if values else 1.0

    def _album_loudness(self, track):
        if self._albums is None:
            groups = collections.defaultdict(list)
            for t in self.library.library_tracks():
                hit = self._lookup(t.path)
                if hit is not None:
                    groups[_album_key(t)].append(hit[0])
            self._albums = {k: loudness.album_lufs(v) for k, v in groups.items()}
        return self._albums.get(_album_key(track))

    def _lookup(self, path):
        known = self._known or {}
        hit = known.get(path)
        if hit is None:
            return None
        key = loudness.file_key(path)
        if key is not None and (abs(key[0] - (hit[0] or 0)) > 1e-3 or key[1] != hit[1]):
            return None                    # the file changed since it was measured
        if hit[2] is None:
            return None, 1.0               # measured: silent / unreadable -> leave it alone
        return hit[2], hit[3] or 1.0

    def _load_known(self):
        if self._known is None:
            self._known = self.library.loudness_all()

    # ------------------------------------------------------------------ worker
    def _start(self):
        if self._thread is None or not self._thread.is_alive():
            self._cancel.clear()
            self._thread = threading.Thread(target=self._run, name="T9Loudness", daemon=True)
            self._thread.start()

    def _next_path(self):
        while self._urgent:
            p = self._urgent.popleft()
            if self._lookup(p) is None:
                return p, True
        while self._background:
            p = self._background.popleft()
            self._queued.discard(p)
            if self._lookup(p) is None:
                return p, False
        return None, False

    def _run(self):
        while not self._cancel.is_set():
            if self.mode == "off":
                self._wake.wait(1.0)
                self._wake.clear()
                continue
            path, urgent = self._next_path()
            if path is None:
                self._wake.wait(2.0)
                self._wake.clear()
                continue
            key = loudness.file_key(path)
            if key is None:
                continue
            try:
                result = loudness.read_tags(path) or loudness.measure(path, self._cancel)
            except Exception as exc:
                _log.warning("loudness of %s: %s", path, exc)
                result = None
            if self._cancel.is_set():
                return
            lufs, peak = result if result else (None, None)
            self._known[path] = (key[0], key[1], lufs, peak)
            self.library.set_loudness(path, key[0], key[1], lufs, peak)
            self._albums = None
            self._done.put(path)
            if not urgent:
                time.sleep(0.05)           # the whole library: gently, the music comes first
