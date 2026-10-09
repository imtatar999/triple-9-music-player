"""Cover art loading off the UI thread: list thumbnails (disk cached) and
full-size covers with a pre-blurred backdrop for the lyrics view."""

import collections
import hashlib
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QImage, QPixmap

from . import meta, paths

THUMB_SIZE = 96


def _thumb_file(path, mtime):
    key = hashlib.sha1(f"{path}|{mtime}".encode("utf-8", "surrogatepass")).hexdigest()
    return os.path.join(paths.THUMB_DIR, key[:2], key + ".jpg")


def _load_image(data):
    if not data:
        return None
    img = QImage()
    if not img.loadFromData(data):
        return None
    return img if not img.isNull() else None


def blur_image(img, width=72, passes=3, radius=3, darken=0.55):
    """Small, heavily blurred and darkened copy (drawn scaled up later)."""
    small = img.scaled(width, width, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    small = small.convertToFormat(QImage.Format_RGB32)
    h, w = small.height(), small.width()
    buf = np.frombuffer(small.constBits(), dtype=np.uint8, count=small.bytesPerLine() * h)
    arr = buf.reshape(h, small.bytesPerLine())[:, : w * 4].reshape(h, w, 4).astype(np.float32)
    k = 2 * radius + 1
    for _ in range(passes):
        pad = np.pad(arr, ((radius, radius), (0, 0), (0, 0)), mode="edge")
        cs = np.cumsum(pad, axis=0)
        cs = np.concatenate([np.zeros((1, w, 4), np.float32), cs], axis=0)
        arr = (cs[k:] - cs[:-k]) / k
        pad = np.pad(arr, ((0, 0), (radius, radius), (0, 0)), mode="edge")
        cs = np.cumsum(pad, axis=1)
        cs = np.concatenate([np.zeros((h, 1, 4), np.float32), cs], axis=1)
        arr = (cs[:, k:] - cs[:, :-k]) / k
    arr[..., :3] *= darken
    arr[..., 3] = 255
    out = np.ascontiguousarray(np.clip(arr, 0, 255).astype(np.uint8))
    result = QImage(out.data, w, h, w * 4, QImage.Format_RGB32)
    return result.copy()   # detach from the numpy buffer


class CoverLoader(QObject):
    thumb_ready = Signal(str)
    cover_ready = Signal(str, object, object)     # path, QImage|None, QImage|None (blurred)
    album_art_ready = Signal(str)                 # album key (a downloaded cover arrived)
    _thumb_done = Signal(object, object)
    _online_done = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        from .musicbrainz import OnlineCovers
        self._pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="T9Cover")
        self._big_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="T9CoverBig")
        self._thumbs = collections.OrderedDict()
        self._pending = set()
        self._lock = threading.Lock()
        self._big_cache = collections.OrderedDict()
        self._thumb_done.connect(self._on_thumb, Qt.QueuedConnection)
        self._online_done.connect(self._on_online, Qt.QueuedConnection)
        self.online = OnlineCovers(self._online_done.emit)
        # album key -> {"source": "songs" | "track" | "file", "path": ...}; missing = automatic
        self.overrides = {}
        self.artist_overrides = {}     # same for artist pictures

    # ------------------------------------------------------------------ thumbnails
    def thumb(self, track, size=THUMB_SIZE):
        """QPixmap, False (no art) or None (loading)."""
        return self._get((track.path, size), track.path, track.mtime, size)

    def _get(self, key, path, mtime, size, source="track"):
        pm = self._thumbs.get(key)
        if pm is not None:
            self._thumbs.move_to_end(key)
            return pm
        with self._lock:
            if key in self._pending:
                return None
            self._pending.add(key)
        self._pool.submit(self._thumb_job, key, path, mtime, size, source)
        return None

    def _album_source(self, album):
        """('file', path) | ('track', path) for the cover an album should show."""
        from . import musicbrainz
        ov = self.overrides.get(album.key) or {}
        kind = ov.get("source")
        if kind == "file" and os.path.isfile(ov.get("path", "")):
            return "file", ov["path"]
        if kind == "track" and os.path.isfile(ov.get("path", "")):
            return "track", ov["path"]
        # the user's own choice always wins; downloads only fill in where nothing was chosen
        if kind in ("lastfm", "musicbrainz"):
            source = "lastfm" if kind == "lastfm" else None
            if musicbrainz.has_online(album.key, "album", source):
                return "file", musicbrainz.online_file(album.key, "album", source)
            self.online.request(album.key, album.title, album.artist, kind)
        elif kind != "songs":
            self.online.request(album.key, album.title, album.artist)
            found = musicbrainz.best_online(album.key, "album")
            if found:
                return "file", found
        return "track", album.cover_track.path

    def album_art(self, album, size=300):
        """Cover for an album tile: the user's choice, else the downloaded official
        cover, else the cover of one of its songs."""
        kind, path = self._album_source(album)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = 0
        if kind == "file":
            return self._get(("album", album.key, size), path, mtime, size, source="file")
        return self._get((path, size), path, mtime, size)

    def _artist_source(self, artist):
        from . import musicbrainz
        ov = self.artist_overrides.get(artist.key) or {}
        kind = ov.get("source")
        if kind in ("file", "track") and os.path.isfile(ov.get("path", "")):
            return kind, ov["path"]
        if kind in ("lastfm", "deezer"):
            source = "lastfm" if kind == "lastfm" else None
            if musicbrainz.has_online(artist.key, "artist", source):
                return "file", musicbrainz.online_file(artist.key, "artist", source)
            self.online.request_artist(artist.key, artist.name, kind)
        elif kind != "songs":
            self.online.request_artist(artist.key, artist.name)
            found = musicbrainz.best_online(artist.key, "artist")
            if found:
                return "file", found
        return "track", artist.cover_track.path

    def artist_art(self, artist, size=300):
        """Picture for an artist tile: the user's choice, a photo from the internet,
        else the cover of their most played song."""
        kind, path = self._artist_source(artist)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = 0
        if kind == "file":
            return self._get(("album", "artist:" + artist.key, size), path, mtime, size, source="file")
        return self._get((path, size), path, mtime, size)

    def artist_image(self, artist):
        kind, path = self._artist_source(artist)
        if kind == "file":
            img = QImage(path)
            if not img.isNull():
                return img
            path = artist.cover_track.path
        return _load_image(meta.cover_bytes(path))

    def album_image(self, album):
        """Full-size QImage for an album page header (blocking, call from a worker)."""
        kind, path = self._album_source(album)
        if kind == "file":
            img = QImage(path)
            if not img.isNull():
                return img
            path = album.cover_track.path
        return _load_image(meta.cover_bytes(path))

    def _thumb_job(self, key, path, mtime, size, source):
        img = None
        try:
            if source == "file":
                full = QImage(path)
                img = None if full.isNull() else _square(full, size)
                self._thumb_done.emit(key, img if img is not None else False)
                return
            cache = _thumb_file(path, mtime) if size == THUMB_SIZE else _thumb_file(f"{path}|{size}", mtime)
            if os.path.isfile(cache):
                img = QImage(cache)
                if img.isNull():
                    img = None
            if img is None:
                if os.path.isfile(_thumb_file(path, mtime) + ".none"):
                    self._thumb_done.emit(key, False)
                    return
                full = _load_image(meta.cover_bytes(path))
                if full is None:
                    try:
                        none = _thumb_file(path, mtime) + ".none"
                        os.makedirs(os.path.dirname(none), exist_ok=True)
                        open(none, "wb").close()
                    except OSError:
                        pass
                    self._thumb_done.emit(key, False)
                    return
                img = _square(full, size)
                try:
                    os.makedirs(os.path.dirname(cache), exist_ok=True)
                    img.save(cache, "JPG", 90)
                except Exception:
                    pass
            self._thumb_done.emit(key, img)
        except Exception:
            self._thumb_done.emit(key, False)

    def _on_thumb(self, key, img):
        with self._lock:
            self._pending.discard(key)
        self._thumbs[key] = QPixmap.fromImage(img) if img else False
        while len(self._thumbs) > 4000:
            self._thumbs.popitem(last=False)
        self.thumb_ready.emit(key[1] if key[0] == "album" else key[0])

    def _on_online(self, album_key):
        for key in [k for k in self._thumbs if k[0] == "album" and k[1] == album_key]:
            self._thumbs.pop(key, None)
        self.album_art_ready.emit(album_key)

    def forget_album(self, album_key):
        for key in [k for k in self._thumbs if k[0] == "album" and k[1] == album_key]:
            self._thumbs.pop(key, None)

    # ------------------------------------------------------------------ full covers
    def request_cover(self, path):
        with self._lock:
            hit = self._big_cache.get(path)
            if hit is not None:
                self._big_cache.move_to_end(path)
        if hit is not None:
            self.cover_ready.emit(path, hit[0], hit[1])
            return
        self._big_pool.submit(self._cover_job, path)

    def _cover_job(self, path):
        cover = blurred = None
        try:
            cover = _load_image(meta.cover_bytes(path))
            if cover is not None:
                if max(cover.width(), cover.height()) > 1400:
                    cover = cover.scaled(1400, 1400, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                blurred = blur_image(cover)
        except Exception:
            cover = blurred = None
        with self._lock:
            self._big_cache[path] = (cover, blurred)
            while len(self._big_cache) > 12:
                self._big_cache.popitem(last=False)
        self.cover_ready.emit(path, cover, blurred)

    def submit(self, fn, *args):
        """Run a cover-related job on the big-cover worker."""
        return self._big_pool.submit(fn, *args)

    def shutdown(self):
        self.online.stop()
        self._pool.shutdown(wait=False, cancel_futures=True)
        self._big_pool.shutdown(wait=False, cancel_futures=True)


def _square(img, size):
    img = img.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    if img.width() != img.height():
        side = min(img.width(), img.height())
        img = img.copy((img.width() - side) // 2, (img.height() - side) // 2, side, side)
    return img


def dominant_color(img):
    """A vivid average colour of an image (for the album page header gradient)."""
    from PySide6.QtGui import QColor
    if img is None or img.isNull():
        return None
    small = img.scaled(24, 24, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).convertToFormat(QImage.Format_RGB32)
    arr = np.frombuffer(small.constBits(), np.uint8, count=small.bytesPerLine() * 24).reshape(24, small.bytesPerLine())
    px = arr[:, :96].reshape(24, 24, 4)[..., :3].reshape(-1, 3).astype(np.float32)[:, ::-1]
    sat = px.max(axis=1) - px.min(axis=1)
    weights = 1.0 + sat / 40.0
    rgb = (px * weights[:, None]).sum(axis=0) / weights.sum()
    c = QColor(int(rgb[0]), int(rgb[1]), int(rgb[2]))
    h, s_, v, _ = c.getHsv()
    return QColor.fromHsv(max(0, h), min(255, int(s_ * 1.25) + 20), max(70, min(150, v)))
