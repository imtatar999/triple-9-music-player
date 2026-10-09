"""Album covers and artist pictures from the internet.

Covers: Last.fm first, MusicBrainz + Cover Art Archive as the alternative.
Artist pictures: Last.fm first, Deezer as the alternative.

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


# sources: covers "lastfm" | "musicbrainz", artist pictures "lastfm" | "deezer"
def online_file(key, kind="album", source=None):
    base = cover_file(key) if kind == "album" else picture_file(key)
    if source == "lastfm":
        return base[:-4] + "_lastfm.jpg"
    return base              # MusicBrainz covers / Deezer pictures (the names from before 1.5)


def _miss_file(key, kind="album", source=None):
    return online_file(key, kind, source)[:-4] + ".miss"


def has_online(key, kind="album", source=None):
    return os.path.isfile(online_file(key, kind, source))


def has_cover(album_key):
    return has_online(album_key, "album")


def has_picture(artist_key):
    return has_online(artist_key, "artist")


def _recently_missed(key, kind="album", source=None):
    try:
        return time.time() - os.path.getmtime(_miss_file(key, kind, source)) < RETRY_MISS_DAYS * 86400
    except OSError:
        return False


def best_online(key, kind="album"):
    """Path of the downloaded picture to show automatically (Last.fm first), or None."""
    for source in ("lastfm", None):
        if has_online(key, kind, source):
            return online_file(key, kind, source)
    return None


def _auto_done(key, kind):
    """Nothing left to try automatically for this album / artist."""
    if has_online(key, kind, "lastfm"):
        return True
    return _recently_missed(key, kind, "lastfm") and (has_online(key, kind) or _recently_missed(key, kind))


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


# Last.fm: the picture of an album / artist page (og:image); no API key needed
_LASTFM_PLACEHOLDERS = ("2a96cbd8b46e442fc41c2b86b821562f", "c6f59c1e5e7240a4c0d427abd71f3dbb",
                        "4128a6eb29f94943c9d206c08e625904")


def find_lastfm_image(artist, album=None):
    """Full-size image URL from the Last.fm page of an album (or an artist), or None."""
    q = urllib.parse.quote_plus
    url = f"https://www.last.fm/music/{q(artist)}" + (f"/{q(album)}" if album else "")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html",
                                               "Accept-Language": "en"})
    try:
        resp = urllib.request.urlopen(req, timeout=15)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    data = b""
    with resp:
        while len(data) < 2_000_000:
            chunk = resp.read(65536)
            if not chunk:
                break
            data += chunk
            m = re.search(rb'<meta property="og:image"\s+content="([^"]+)"', data)
            if m:
                image = m.group(1).decode("utf-8", "replace")
                if not image.startswith("https://") or any(p in image for p in _LASTFM_PLACEHOLDERS):
                    return None
                return image
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

    def request(self, album_key, title, artist, source="auto"):
        """source: "auto" (Last.fm, else MusicBrainz), "lastfm" or "musicbrainz"."""
        if not self.enabled or not title or not artist or artist.casefold() in ("various artists", "unknown artist"):
            return
        self._put("album", album_key, title, artist, source)

    def request_artist(self, artist_key, name, source="auto"):
        """source: "auto" (Last.fm, else Deezer), "lastfm" or "deezer"."""
        if not self.enabled or not name or name.casefold() in ("various artists", "unknown artist"):
            return
        self._put("artist", artist_key, name, None, source)

    def _put(self, kind, key, title, artist, source):
        file_source = "lastfm" if source == "lastfm" else None
        if source == "auto":
            if _auto_done(key, kind):
                return
        elif has_online(key, kind, file_source) or _recently_missed(key, kind, file_source):
            return
        with self._lock:
            if (kind, key, source) in self._queued:
                return
            self._queued.add((kind, key, source))
        self._queue.put((kind, key, title, artist, source))

    def _run(self):
        last = 0.0
        while True:
            kind, key, title, artist, source = self._queue.get()
            if kind is None:
                return
            try:
                if not self.enabled or time.time() < self._offline_until:
                    continue
                for step in (("lastfm", "musicbrainz" if kind == "album" else "deezer") if source == "auto"
                             else (source,)):
                    file_source = "lastfm" if step == "lastfm" else None
                    if has_online(key, kind, file_source):
                        break                       # already here (e.g. chosen before)
                    if _recently_missed(key, kind, file_source):
                        continue
                    wait = 1.2 - (time.time() - last)
                    if wait > 0:
                        time.sleep(wait)
                    last = time.time()
                    if self._fetch_one(kind, key, title, artist, step):
                        break
            except (urllib.error.URLError, OSError, TimeoutError):
                # no internet (or the service is down): stay quiet and retry later in the session
                self._offline_until = time.time() + 600
            except Exception:
                pass
            finally:
                with self._lock:
                    self._queued.discard((kind, key, source))

    def _fetch_one(self, kind, key, title, artist, source):
        """Download one picture from one source; True when it was found."""
        file_source = "lastfm" if source == "lastfm" else None
        if source == "lastfm":
            url = find_lastfm_image(artist, title) if kind == "album" else find_lastfm_image(title)
        elif source == "musicbrainz":
            rgid = find_release_group(title, artist)
            url = f"https://coverartarchive.org/release-group/{rgid}/front-500" if rgid else None
        else:
            url = find_artist_picture(title)
        if not url:
            self._mark_miss(key, kind, file_source)
            return False
        try:
            data = _get(url, timeout=15)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                self._mark_miss(key, kind, file_source)
                return False
            raise
        if len(data) < 2000:
            self._mark_miss(key, kind, file_source)
            return False
        path = online_file(key, kind, file_source)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".tmp", "wb") as handle:
            handle.write(data)
        os.replace(path + ".tmp", path)
        self.on_ready(key if kind == "album" else "artist:" + key)
        return True

    def _mark_miss(self, key, kind="album", source=None):
        try:
            os.makedirs(COVER_DIR if kind == "album" else ARTIST_DIR, exist_ok=True)
            open(_miss_file(key, kind, source), "wb").close()
        except OSError:
            pass

    def stop(self):
        self._queue.put((None, None, None, None, None))
