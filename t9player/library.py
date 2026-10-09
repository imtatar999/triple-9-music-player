"""Music library: SQLite storage, background folder scanning, playlists."""

import os
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import meta

SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    mtime REAL, size INTEGER,
    title TEXT, artist TEXT, album TEXT, albumartist TEXT, year TEXT,
    track INTEGER, disc INTEGER, genre TEXT,
    duration REAL, samplerate INTEGER, bits INTEGER, channels INTEGER,
    bitrate INTEGER, codec TEXT,
    added REAL, plays INTEGER DEFAULT 0, last_played REAL DEFAULT 0,
    favorite INTEGER DEFAULT 0, lyrics_offset REAL DEFAULT 0,
    in_library INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS playlists (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, created REAL
);
CREATE TABLE IF NOT EXISTS playlist_items (
    playlist_id INTEGER NOT NULL, pos INTEGER NOT NULL, path TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_items ON playlist_items(playlist_id, pos);
"""

FIELDS = ("path", "mtime", "size", "title", "artist", "album", "albumartist", "year",
          "track", "disc", "genre", "duration", "samplerate", "bits", "channels",
          "bitrate", "codec")


class Track:
    """Lightweight in-memory row. Attribute access only, no Qt."""
    __slots__ = FIELDS + ("id", "added", "plays", "last_played", "favorite",
                          "lyrics_offset", "in_library", "_search", "_label")

    def __init__(self, **kw):
        for name in self.__slots__:
            setattr(self, name, kw.get(name))
        self.title = self.title or os.path.splitext(os.path.basename(self.path or ""))[0]
        self.artist = self.artist or ""
        self.album = self.album or ""
        self.albumartist = self.albumartist or ""
        self.year = self.year or ""
        self.genre = self.genre or ""
        self.codec = self.codec or ""
        for name in ("track", "disc", "samplerate", "bits", "channels", "bitrate", "plays", "favorite", "size"):
            setattr(self, name, int(getattr(self, name) or 0))
        for name in ("duration", "mtime", "added", "last_played", "lyrics_offset"):
            setattr(self, name, float(getattr(self, name) or 0.0))
        self.in_library = 1 if self.in_library is None else int(self.in_library)
        self._search = None
        self._label = None

    @property
    def search_text(self):
        if self._search is None:
            self._search = " ".join((self.title, self.artist, self.album, self.albumartist,
                                     self.genre, self.year)).casefold()
        return self._search

    @property
    def format_label(self):
        if self._label is None:
            self._label = meta.format_label(self.codec, self.samplerate, self.bits, self.bitrate)
        return self._label

    @property
    def hires(self):
        return meta.is_hires(self.samplerate, self.bits)

    @property
    def display_artist(self):
        return self.artist or self.albumartist or "Unknown artist"

    @classmethod
    def from_info(cls, info):
        return cls(**{k: info.get(k) for k in FIELDS})


def connect(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.DatabaseError:
        pass
    conn.executescript(SCHEMA)
    return conn


class Library:
    """Thread-safe facade over the database plus the in-memory track list."""

    def __init__(self, db_path):
        self.db_path = db_path
        self._lock = threading.RLock()
        try:
            self.conn = connect(db_path)
        except sqlite3.DatabaseError:
            # corrupted database: keep a copy for the user and start fresh
            try:
                os.replace(db_path, db_path + f".broken-{int(time.time())}")
            except OSError:
                pass
            self.conn = connect(db_path)
        self.tracks = {}          # path -> Track
        self._scan_thread = None
        self._scan_cancel = threading.Event()

    # ------------------------------------------------------------------ loading
    def load(self):
        with self._lock:
            rows = self.conn.execute("SELECT * FROM tracks").fetchall()
        tracks = {}
        for row in rows:
            t = Track(**dict(row))
            tracks[t.path] = t
        self.tracks = tracks
        return list(tracks.values())

    def library_tracks(self):
        return [t for t in list(self.tracks.values()) if t.in_library]

    def get(self, path):
        return self.tracks.get(path)

    def track_for_path(self, path):
        """Track object for any file, reading tags for files outside the library."""
        t = self.tracks.get(path)
        if t is not None:
            return t
        info = meta.read_tags(path)
        t = Track.from_info(info)
        t.in_library = 0
        t.added = time.time()
        self._upsert([t])
        self.tracks[path] = t
        return t

    # ------------------------------------------------------------------ writes
    def _upsert(self, tracks):
        cols = FIELDS + ("added", "in_library")
        sql = (f"INSERT INTO tracks ({','.join(cols)}) VALUES ({','.join('?' * len(cols))}) "
               "ON CONFLICT(path) DO UPDATE SET " +
               ",".join(f"{c}=excluded.{c}" for c in FIELDS) +
               ", in_library=MAX(in_library, excluded.in_library)")
        with self._lock:
            self.conn.executemany(sql, [tuple(getattr(t, c) for c in cols) for t in tracks])
            self.conn.commit()

    def _update(self, path, **values):
        if not values:
            return
        sets = ",".join(f"{k}=?" for k in values)
        try:
            with self._lock:
                self.conn.execute(f"UPDATE tracks SET {sets} WHERE path=?", (*values.values(), path))
                self.conn.commit()
        except sqlite3.DatabaseError:
            pass

    def set_favorite(self, track, value):
        track.favorite = 1 if value else 0
        self._update(track.path, favorite=track.favorite)

    def set_lyrics_offset(self, track, value):
        track.lyrics_offset = float(value)
        self._update(track.path, lyrics_offset=track.lyrics_offset)

    def count_play(self, track):
        track.plays += 1
        track.last_played = time.time()
        self._update(track.path, plays=track.plays, last_played=track.last_played)

    # ------------------------------------------------------------------ scanning
    def scan(self, folders, on_progress=None, on_done=None):
        """Incremental background scan. Callbacks run in the scan thread."""
        self.cancel_scan()
        self._scan_cancel = threading.Event()
        cancel = self._scan_cancel
        self._scan_thread = threading.Thread(
            target=self._scan_worker, args=(list(folders), cancel, on_progress, on_done),
            name="T9LibraryScan", daemon=True)
        self._scan_thread.start()

    def cancel_scan(self):
        self._scan_cancel.set()
        thread = self._scan_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)

    @property
    def scanning(self):
        return self._scan_thread is not None and self._scan_thread.is_alive()

    def _walk(self, folders, cancel):
        found = {}
        stack = [f for f in folders if f and os.path.isdir(f)]
        seen = set()
        while stack and not cancel.is_set():
            folder = stack.pop()
            try:
                real = os.path.realpath(folder)
            except OSError:
                continue
            if real in seen:
                continue
            seen.add(real)
            try:
                with os.scandir(folder) as it:
                    for entry in it:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                if not entry.name.startswith("."):
                                    stack.append(entry.path)
                            elif meta.is_audio(entry.name):
                                st = entry.stat()
                                found[os.path.normpath(entry.path)] = (st.st_mtime, st.st_size)
                        except OSError:
                            continue
            except OSError:
                continue
        return found

    def _scan_worker(self, folders, cancel, on_progress, on_done):
        added = updated = removed = 0
        try:
            found = self._walk(folders, cancel)
            if cancel.is_set():
                return
            known = dict(self.tracks)
            todo = []
            for path, (mtime, size) in found.items():
                t = known.get(path)
                if t is None or abs(t.mtime - mtime) > 1e-3 or t.size != size or not t.in_library:
                    todo.append(path)
            gone = [p for p, t in known.items() if t.in_library and p not in found
                    and _under_any(p, folders)]
            total = len(todo)
            if on_progress:
                on_progress(0, total, [])
            batch = []
            now = time.time()
            done = 0
            with ThreadPoolExecutor(max_workers=4) as pool:
                for info in pool.map(meta.read_tags, todo):
                    if cancel.is_set():
                        break
                    t = Track.from_info(info)
                    old = known.get(t.path)
                    if old is not None:
                        t.added = old.added or now
                        t.plays, t.favorite, t.last_played = old.plays, old.favorite, old.last_played
                        t.lyrics_offset, t.id = old.lyrics_offset, old.id
                        updated += 1
                    else:
                        t.added = now
                        added += 1
                    t.in_library = 1
                    batch.append(t)
                    done += 1
                    if len(batch) >= 200:
                        self._commit_batch(batch)
                        if on_progress:
                            on_progress(done, total, batch)
                        batch = []
            if batch:
                self._commit_batch(batch)
                if on_progress:
                    on_progress(done, total, batch)
            if gone and not cancel.is_set():
                with self._lock:
                    self.conn.executemany("UPDATE tracks SET in_library=0 WHERE path=?", [(p,) for p in gone])
                    self.conn.commit()
                for p in gone:
                    t = self.tracks.get(p)
                    if t is not None:
                        t.in_library = 0
                removed = len(gone)
        except Exception as exc:   # never let a scan take the app down
            if on_done:
                on_done({"error": str(exc), "added": added, "updated": updated, "removed": removed})
            return
        if on_done:
            on_done({"added": added, "updated": updated, "removed": removed, "cancelled": cancel.is_set()})

    def _commit_batch(self, batch):
        try:
            self._upsert(batch)
        except sqlite3.DatabaseError:
            return
        for t in batch:
            self.tracks[t.path] = t

    def remove_folder_tracks(self, folder, remaining):
        """Hide tracks of a folder the user removed from the library."""
        hide = [p for p, t in list(self.tracks.items()) if t.in_library and _under_any(p, [folder])
                and not _under_any(p, remaining)]
        if not hide:
            return 0
        with self._lock:
            self.conn.executemany("UPDATE tracks SET in_library=0 WHERE path=?", [(p,) for p in hide])
            self.conn.commit()
        for p in hide:
            self.tracks[p].in_library = 0
        return len(hide)

    # ------------------------------------------------------------------ playlists
    def playlists(self):
        with self._lock:
            rows = self.conn.execute("SELECT id, name FROM playlists ORDER BY name COLLATE NOCASE").fetchall()
        return [(r["id"], r["name"]) for r in rows]

    def create_playlist(self, name):
        with self._lock:
            cur = self.conn.execute("INSERT INTO playlists (name, created) VALUES (?, ?)", (name, time.time()))
            self.conn.commit()
            return cur.lastrowid

    def rename_playlist(self, pid, name):
        with self._lock:
            self.conn.execute("UPDATE playlists SET name=? WHERE id=?", (name, pid))
            self.conn.commit()

    def delete_playlist(self, pid):
        with self._lock:
            self.conn.execute("DELETE FROM playlist_items WHERE playlist_id=?", (pid,))
            self.conn.execute("DELETE FROM playlists WHERE id=?", (pid,))
            self.conn.commit()

    def playlist_paths(self, pid):
        with self._lock:
            rows = self.conn.execute("SELECT path FROM playlist_items WHERE playlist_id=? ORDER BY pos", (pid,)).fetchall()
        return [r["path"] for r in rows]

    def playlist_tracks(self, pid):
        out = []
        for path in self.playlist_paths(pid):
            t = self.tracks.get(path)
            if t is None and os.path.isfile(path):
                try:
                    t = self.track_for_path(path)
                except Exception:
                    t = None
            if t is not None:
                out.append(t)
        return out

    def set_playlist_paths(self, pid, paths):
        with self._lock:
            self.conn.execute("DELETE FROM playlist_items WHERE playlist_id=?", (pid,))
            self.conn.executemany("INSERT INTO playlist_items (playlist_id, pos, path) VALUES (?, ?, ?)",
                                  [(pid, i, p) for i, p in enumerate(paths)])
            self.conn.commit()

    def add_to_playlist(self, pid, paths):
        current = self.playlist_paths(pid)
        self.set_playlist_paths(pid, current + [p for p in paths])

    def close(self):
        self.cancel_scan()
        try:
            with self._lock:
                self.conn.close()
        except Exception:
            pass


def _under_any(path, folders):
    p = os.path.normcase(os.path.normpath(path))
    for folder in folders:
        f = os.path.normcase(os.path.normpath(folder))
        if p == f or p.startswith(f.rstrip("\\/") + os.sep):
            return True
    return False


# --------------------------------------------------------------------------- m3u

def read_m3u(path):
    from .lyrics import decode_text_file
    try:
        with open(path, "rb") as handle:
            text = decode_text_file(handle.read())
    except OSError:
        return []
    base = os.path.dirname(path)
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("file:///"):
            from urllib.parse import unquote
            line = unquote(line[8:])
        full = line if os.path.isabs(line) else os.path.join(base, line)
        full = os.path.normpath(full)
        if os.path.isfile(full) and meta.is_audio(full):
            out.append(full)
    return out


def write_m3u(path, tracks):
    lines = ["#EXTM3U"]
    for t in tracks:
        lines.append(f"#EXTINF:{int(t.duration)},{t.display_artist} - {t.title}")
        lines.append(t.path)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
