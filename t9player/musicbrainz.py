"""Official album covers (MusicBrainz + Cover Art Archive) and artist pictures (Deezer).

Runs in one background thread, at most one request per ~1.2 s (MusicBrainz asks
for <= 1/s), results are cached on disk. Only a confident match is accepted
(same album title, same artist), so fan compilations like "JW3 (Outsiders)"
simply keep the cover from their songs. No connection = nothing happens.
"""

import hashlib
import json
import os
import queue
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import APP_VERSION, paths

COVER_DIR = os.path.join(paths.DATA_DIR, "album_covers")
ARTIST_DIR = os.path.join(paths.DATA_DIR, "artist_pictures")
USER_AGENT = f"T9MusicPlayer/{APP_VERSION} (personal desktop music player)"
RETRY_MISS_DAYS = 30


def cover_file(album_key):
    h = hashlib.sha1(album_key.encode("utf-8", "surrogatepass")).hexdigest()
    return os.path.join(COVER_DIR, h + ".jpg")


def picture_file(artist_key):
    h = hashlib.sha1(("artist:" + artist_key).encode("utf-8", "surrogatepass")).hexdigest()
    return os.path.join(ARTIST_DIR, h + ".jpg")


def _miss_file(key, kind="album"):
    return (cover_file(key) if kind == "album" else picture_file(key))[:-4] + ".miss"


def has_cover(album_key):
    return os.path.isfile(cover_file(album_key))


def has_picture(artist_key):
    return os.path.isfile(picture_file(artist_key))


def _recently_missed(key, kind="album"):
    try:
        return time.time() - os.path.getmtime(_miss_file(key, kind)) < RETRY_MISS_DAYS * 86400
    except OSError:
        return False


def _simplify(text):
    text = (text or "").casefold().replace("&", " and ")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _get(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def find_release_group(title, artist):
    """MusicBrainz release-group id for an album, or None when there is no confident match."""
    def esc(s):
        return re.sub(r'([+\-&|!(){}\[\]^"~*?:\\/])', r"\\\1", s)

    query = f'releasegroup:"{esc(title)}" AND artist:"{esc(artist)}"'
    url = "https://musicbrainz.org/ws/2/release-group/?" + urllib.parse.urlencode(
        {"query": query, "fmt": "json", "limit": 5})
    data = json.loads(_get(url).decode("utf-8"))
    want_title, want_artist = _simplify(title), _simplify(artist)
    for rg in data.get("release-groups", []):
        if int(rg.get("score", 0)) < 90:
            continue
        if _simplify(rg.get("title")) != want_title:
            continue
        credits = [_simplify(c.get("name") or c.get("artist", {}).get("name", ""))
                   for c in rg.get("artist-credit", []) if isinstance(c, dict)]
        if want_artist and want_artist not in credits:
            continue
        return rg.get("id")
    return None


def find_artist_picture(name):
    """URL of an artist photo on Deezer, or None when no artist with exactly this name has one."""
    url = "https://api.deezer.com/search/artist?" + urllib.parse.urlencode({"q": name, "limit": 10})
    data = json.loads(_get(url).decode("utf-8"))
    want = _simplify(name)
    for item in data.get("data", []):
        if _simplify(item.get("name")) != want:
            continue
        pic = item.get("picture_xl") or item.get("picture_big") or ""
        # Deezer's placeholder for artists without a photo has an empty id in the path
        if not pic or "/artist//" in pic:
            return None
        return pic
    return None


class OnlineCovers:
    """Background fetcher. `on_ready(album_key)` is called from its thread."""

    def __init__(self, on_ready):
        self.on_ready = on_ready
        self.enabled = True
        self._queue = queue.Queue()
        self._queued = set()
        self._offline_until = 0.0
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, name="T9MusicBrainz", daemon=True)
        self._thread.start()

    def request(self, album_key, title, artist):
        if not self.enabled or not title or not artist or artist.casefold() in ("various artists", "unknown artist"):
            return
        if has_cover(album_key) or _recently_missed(album_key):
            return
        with self._lock:
            if album_key in self._queued:
                return
            self._queued.add(album_key)
        self._queue.put(("album", album_key, title, artist))

    def request_artist(self, artist_key, name):
        if not self.enabled or not name or name.casefold() in ("various artists", "unknown artist"):
            return
        if has_picture(artist_key) or _recently_missed(artist_key, "artist"):
            return
        with self._lock:
            if ("artist", artist_key) in self._queued:
                return
            self._queued.add(("artist", artist_key))
        self._queue.put(("artist", artist_key, name, None))

    def _run(self):
        last = 0.0
        while True:
            kind, album_key, title, artist = self._queue.get()
            if kind is None:
                return
            try:
                if not self.enabled or time.time() < self._offline_until:
                    continue
                wait = 1.2 - (time.time() - last)
                if wait > 0:
                    time.sleep(wait)
                last = time.time()
                if kind == "artist":
                    self._fetch_artist(album_key, title)
                else:
                    self._fetch(album_key, title, artist)
            except (urllib.error.URLError, OSError, TimeoutError):
                # no internet (or the service is down): stay quiet and retry later in the session
                self._offline_until = time.time() + 600
                with self._lock:
                    self._queued.discard(album_key if kind == "album" else ("artist", album_key))
            except Exception:
                pass

    def _fetch(self, album_key, title, artist):
        rgid = find_release_group(title, artist)
        if not rgid:
            self._mark_miss(album_key)
            return
        try:
            data = _get(f"https://coverartarchive.org/release-group/{rgid}/front-500", timeout=15)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                self._mark_miss(album_key)
                return
            raise
        if len(data) < 2000:
            self._mark_miss(album_key)
            return
        os.makedirs(COVER_DIR, exist_ok=True)
        path = cover_file(album_key)
        tmp = path + ".tmp"
        with open(tmp, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
        self.on_ready(album_key)

    def _fetch_artist(self, artist_key, name):
        pic = find_artist_picture(name)
        if not pic:
            self._mark_miss(artist_key, "artist")
            return
        data = _get(pic, timeout=15)
        if len(data) < 2000:
            self._mark_miss(artist_key, "artist")
            return
        os.makedirs(ARTIST_DIR, exist_ok=True)
        path = picture_file(artist_key)
        with open(path + ".tmp", "wb") as handle:
            handle.write(data)
        os.replace(path + ".tmp", path)
        self.on_ready("artist:" + artist_key)

    def _mark_miss(self, key, kind="album"):
        try:
            os.makedirs(COVER_DIR if kind == "album" else ARTIST_DIR, exist_ok=True)
            open(_miss_file(key, kind), "wb").close()
        except OSError:
            pass

    def stop(self):
        self._queue.put((None, None, None, None))
