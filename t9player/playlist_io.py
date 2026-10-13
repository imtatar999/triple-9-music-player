"""Playlist files in and out.

Import: .m3u/.m3u8 (most players, foobar2000's export), .pls (Winamp), .xspf (VLC), .json (Ampwave),
.fpl/.fplite (foobar2000's own playlists), .wpl/.zpl (Windows Media Player / Zune), .asx, .txt (one path per line).
Export: .m3u8, .pls, .xspf, .wpl, .json.

Importing matches every entry to a song in the library, most reliable first:
  1. the exact path (absolute, or relative to the playlist file),
  2. the end of the path (the same folders/file under a different drive or music folder),
  3. a file name that only one song has,
  4. the tags: title + artist (album and length break ties).
So a playlist made on another computer, by another player (foobar2000, MusicBee, Winamp, VLC,
AIMP, Ampwave ...) or by us with different folders still finds your songs.

The .json export uses the same layout as Ampwave's portable playlists, so the two can swap them.
"""

import json
import os
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from urllib.parse import unquote, urlparse

from . import meta

IMPORT_EXTS = (".m3u", ".m3u8", ".pls", ".xspf", ".json", ".fpl", ".fplite", ".wpl", ".zpl", ".asx", ".txt")


class Entry:
    """One line of a playlist file: whatever the file tells us about the song."""
    __slots__ = ("path", "title", "artist", "album", "duration")

    def __init__(self, path="", title="", artist="", album="", duration=0.0):
        self.path, self.title, self.artist, self.album = path or "", title or "", artist or "", album or ""
        try:
            self.duration = max(0.0, float(duration or 0))
        except (TypeError, ValueError):
            self.duration = 0.0

    def label(self):
        if self.title:
            return f"{self.artist} - {self.title}" if self.artist else self.title
        return os.path.basename(self.path.replace("\\", "/")) or "?"


# ------------------------------------------------------------------------------------ reading

def _read_text(path):
    from .lyrics import decode_text_file
    with open(path, "rb") as handle:
        return decode_text_file(handle.read()).lstrip("\ufeff")


def _clean_path(raw):
    # file names may start with spaces: only cut them off around a quoted path
    p = raw.rstrip()
    if p.strip().startswith('"') and p.strip().endswith('"'):
        p = p.strip()[1:-1]
    if p.lower().startswith("file:"):
        u = urlparse(p)
        p = unquote(u.path)
        if u.netloc and u.netloc.lower() != "localhost":
            p = "//" + u.netloc + p                 # file://server/share/...
        if re.match(r"^/[A-Za-z]:", p):
            p = p[1:]                               # file:///C:/... -> C:/...
    return p


def _split_artist_title(text):
    if " - " in text:
        artist, title = text.split(" - ", 1)
        return artist.strip(), title.strip()
    return "", text.strip()


def _parse_m3u(text):
    name, entries = "", []
    pending = Entry()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        upper = line.upper()
        if upper.startswith("#PLAYLIST:"):
            name = line[10:].strip()
        elif upper.startswith("#EXTINF:"):
            body = line[8:]
            length, _, info = body.partition(",")
            try:
                pending.duration = max(0.0, float(length.split()[0]))
            except (ValueError, IndexError):
                pass
            pending.artist, pending.title = _split_artist_title(info)
        elif upper.startswith("#EXTALB:"):
            pending.album = line[8:].strip()
        elif upper.startswith("#EXTART:"):
            pending.artist = pending.artist or line[8:].strip()
        elif upper.startswith("#AMPWAVE-ALBUM:"):
            pending.album = line[15:].strip()
        elif line.startswith("#"):
            continue
        else:
            raw = _clean_path(raw_line)
            looks_like_path = ("/" in raw or "\\" in raw or os.path.splitext(raw)[1].lower() in meta.AUDIO_EXTS)
            if looks_like_path:
                pending.path = raw
            elif not pending.title:              # Ampwave writes "Artist - Title" instead of a path
                pending.artist, pending.title = _split_artist_title(raw)
            entries.append(pending)
            pending = Entry()
    return name, entries


def _parse_pls(text):
    files, titles, lengths = {}, {}, {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip().lower()
        m = re.match(r"(file|title|length)(\d+)$", key)
        if not m:
            continue
        kind, n = m.group(1), int(m.group(2))
        {"file": files, "title": titles, "length": lengths}[kind][n] = value.strip()
    out = []
    for n in sorted(files):
        artist, title = _split_artist_title(titles.get(n, ""))
        out.append(Entry(_clean_path(files[n]), title, artist, "", lengths.get(n, 0)))
    return "", out


def _parse_xspf(text):
    root = ET.fromstring(text.encode("utf-8"))

    def local(tag):
        return tag.rsplit("}", 1)[-1]

    def child(node, name):
        for c in node:
            if local(c.tag) == name:
                return (c.text or "").strip()
        return ""
    name = child(root, "title")
    out = []
    for node in root.iter():
        if local(node.tag) != "track":
            continue
        ms = child(node, "duration")
        out.append(Entry(_clean_path(child(node, "location")), child(node, "title"), child(node, "creator"),
                         child(node, "album"), (float(ms) / 1000.0) if ms.replace(".", "", 1).isdigit() else 0))
    return name, out


def _parse_json(text):
    data = json.loads(text)
    out = []
    for t in data.get("tracks") or []:
        if not isinstance(t, dict):
            continue
        out.append(Entry(_clean_path(t.get("filePath") or t.get("path") or ""),
                         t.get("songName") or t.get("title") or "",
                         t.get("artistName") or t.get("artist") or "",
                         t.get("albumName") or t.get("album") or "",
                         t.get("duration") or 0))
    return str(data.get("name") or ""), out


def _parse_fpl(data):
    """foobar2000's own binary playlist (.fpl, v1.x): the paths are stored as 'file://C:\\...' strings
    ending in a zero byte, in playlist order. The tags in it are not needed - we read them from the files."""
    out = []
    for m in re.finditer(rb"file://([^\x00]+)\x00", data):
        try:
            p = m.group(1).decode("utf-8")
        except UnicodeDecodeError:
            continue
        if meta.is_audio(p) or os.path.splitext(p)[1] == "":
            out.append(Entry(p.replace("/", "\\") if re.match(r"^[A-Za-z]:", p) else p))
    return "", out


def _parse_xml_list(text):
    """Windows Media Player .wpl / Zune .zpl (<media src=...>) and .asx (<entry><ref href=...>)."""
    root = ET.fromstring(re.sub(r"&(?!(amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)", "&amp;", text).encode("utf-8"))

    def local(tag):
        return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""
    name = ""
    for node in root.iter():
        if local(node.tag) == "title" and (node.text or "").strip():
            name = node.text.strip()
            break
    out = []
    for node in root.iter():
        tag = local(node.tag)
        if tag == "media":
            attrs = {k.lower(): v for k, v in node.attrib.items()}
            if attrs.get("src"):
                out.append(Entry(_clean_path(attrs["src"]), attrs.get("tracktitle", ""),
                                 attrs.get("trackartist", ""), attrs.get("albumtitle", ""),
                                 float(attrs["duration"]) / 1000 if attrs.get("duration", "").isdigit() else 0))
        elif tag == "entry":
            href, title, artist = "", "", ""
            for c in node:
                t = local(c.tag)
                if t == "ref" and not href:
                    href = {k.lower(): v for k, v in c.attrib.items()}.get("href", "")
                elif t == "title":
                    title = (c.text or "").strip()
                elif t == "author":
                    artist = (c.text or "").strip()
            if href:
                out.append(Entry(_clean_path(href), title, artist))
    if local(root.tag) == "asx":
        name = next((c.text.strip() for c in root if local(c.tag) == "title" and c.text), "")
    return name, out


def read(path):
    """-> (playlist name, [Entry]). Raises OSError / ValueError for unreadable files."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".fpl":
        with open(path, "rb") as handle:
            return os.path.splitext(os.path.basename(path))[0], _parse_fpl(handle.read())[1]
    text = _read_text(path)
    stripped = text.lstrip()
    try:
        if ext == ".json" or stripped.startswith("{"):
            name, entries = _parse_json(text)
        elif ext in (".wpl", ".zpl", ".asx") or re.match(r"(<\?[^>]*\?>\s*)*<(smil|asx)\b", stripped, re.I):
            name, entries = _parse_xml_list(text)
        elif ext == ".xspf" or stripped.startswith("<"):
            name, entries = _parse_xspf(text)
        elif ext == ".pls" or stripped.lower().startswith("[playlist]"):
            name, entries = _parse_pls(text)
        else:
            name, entries = _parse_m3u(text)
    except (json.JSONDecodeError, ET.ParseError, AttributeError) as exc:
        raise ValueError(str(exc)) from exc
    return name or os.path.splitext(os.path.basename(path))[0], entries


# ------------------------------------------------------------------------------------ matching

def _norm(text):
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii").casefold()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", text)).strip()


def _path_key(path):
    p = path.replace("\\", "/")
    p = re.sub(r"^[A-Za-z]:/", "", p).lstrip("/")
    parts = [x for x in p.split("/") if x not in ("", ".", "..")]
    return "/".join(parts).casefold()


class Matcher:
    """Finds library songs for playlist entries. Build once per import (indexes the library)."""

    def __init__(self, tracks):
        self.tracks = [t for t in tracks if t.path]
        self.by_path = {os.path.normcase(os.path.normpath(t.path)): t for t in self.tracks}
        self.by_name = {}
        self.by_tags = {}
        for t in self.tracks:
            self.by_name.setdefault(os.path.basename(t.path).casefold(), []).append(t)
            self.by_tags.setdefault((_norm(t.title), _norm(t.display_artist)), []).append(t)
            if t.albumartist and _norm(t.albumartist) != _norm(t.display_artist):
                self.by_tags.setdefault((_norm(t.title), _norm(t.albumartist)), []).append(t)
        self.keys = [(_path_key(t.path), t) for t in self.tracks]

    def find(self, entry, playlist_dir=""):
        """-> (path or None, how it was found)."""
        raw = entry.path
        if raw:
            native = raw.replace("/", os.sep) if os.sep == "\\" else raw.replace("\\", "/")
            candidates = [native] if os.path.isabs(native) else []
            if playlist_dir and not os.path.isabs(native):
                candidates.append(os.path.join(playlist_dir, native))
            for c in candidates:
                key = os.path.normcase(os.path.normpath(c))
                if key in self.by_path:
                    return self.by_path[key].path, "path"
                if os.path.isfile(c) and meta.is_audio(c):
                    return os.path.normpath(c), "path"       # a song outside the library is fine too
            # the same folders under another drive / music folder
            want = _path_key(raw)
            parts = want.split("/")
            for depth in range(min(len(parts), 4), 1, -1):
                tail = "/".join(parts[-depth:])
                hits = [t for k, t in self.keys if k == tail or k.endswith("/" + tail)]
                if len(hits) == 1:
                    return hits[0].path, "folders"
                if hits:
                    best = self._by_tags_among(entry, hits)
                    if best:
                        return best.path, "folders"
                    break
            hits = self.by_name.get(parts[-1], [])
            if len(hits) == 1:
                return hits[0].path, "file name"
            if hits:
                best = self._by_tags_among(entry, hits)
                if best:
                    return best.path, "file name"
        if entry.title:
            hits = self.by_tags.get((_norm(entry.title), _norm(entry.artist)), [])
            if not hits and not entry.artist:
                title = _norm(entry.title)
                hits = [t for (ti, _), ts in self.by_tags.items() if ti == title for t in ts]
            best = self._best(entry, hits)
            if best:
                return best.path, "tags"
        return None, ""

    def _by_tags_among(self, entry, hits):
        if not entry.title:
            return self._best(entry, hits)
        title = _norm(entry.title)
        return self._best(entry, [t for t in hits if _norm(t.title) == title] or hits)

    @staticmethod
    def _best(entry, hits):
        hits = list(dict.fromkeys(hits))
        if not hits:
            return None
        if len(hits) == 1:
            t = hits[0]
            if entry.duration and t.duration and abs(t.duration - entry.duration) > 20:
                return None            # same name, clearly another recording
            return t

        def score(t):
            s = 0.0
            if entry.album and _norm(entry.album) == _norm(t.album):
                s += 2
            if entry.duration and t.duration:
                d = abs(t.duration - entry.duration)
                s += 2.5 if d <= 1.5 else 1 if d <= 4 else -min(d / 10, 2.5)
            return s, t.plays
        return max(hits, key=score)


def resolve(entries, tracks, playlist_path=""):
    """-> (paths found in playlist order, entries not found)."""
    matcher = Matcher(tracks)
    folder = os.path.dirname(playlist_path) if playlist_path else ""
    found, missing = [], []
    for e in entries:
        path, _ = matcher.find(e, folder)
        if path:
            found.append(path)
        else:
            missing.append(e)
    return found, missing


# ------------------------------------------------------------------------------------ writing

def _rel_or_abs(track_path, target, relative):
    if relative:
        try:
            rel = os.path.relpath(track_path, os.path.dirname(target))
        except ValueError:          # another drive
            return track_path
        if rel[:1] in ("#", " ", "\t"):
            rel = "." + os.sep + rel     # '#1 Hit.mp3' would read as a comment, ' x.mp3' would lose its space
        return rel
    return track_path


def write(target, name, tracks, relative=True):
    """Save `tracks` to `target`; the format follows the extension."""
    ext = os.path.splitext(target)[1].lower()
    if ext == ".json":
        payload = {
            "format": "ampwave-playlist", "version": 2, "name": name,
            "exportedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "generator": "Triple 9 Music Player",
            "tracks": [{"songName": t.title, "artistName": t.display_artist, "albumName": t.album or None,
                        "duration": round(t.duration, 3) if t.duration else None,
                        "filePath": _rel_or_abs(t.path, target, relative)} for t in tracks],
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2)
    elif ext == ".pls":
        lines = ["[playlist]"]
        for i, t in enumerate(tracks, 1):
            lines += [f"File{i}={_rel_or_abs(t.path, target, relative)}",
                      f"Title{i}={t.display_artist} - {t.title}", f"Length{i}={int(round(t.duration)) or -1}"]
        lines += [f"NumberOfEntries={len(tracks)}", "Version=2"]
        text = "\n".join(lines) + "\n"
    elif ext in (".wpl", ".zpl"):
        root = ET.Element("smil")
        head = ET.SubElement(root, "head")
        ET.SubElement(head, "meta", {"name": "Generator", "content": "Triple 9 Music Player"})
        ET.SubElement(head, "meta", {"name": "ItemCount", "content": str(len(tracks))})
        ET.SubElement(head, "title").text = name
        seq = ET.SubElement(ET.SubElement(root, "body"), "seq")
        for t in tracks:
            ET.SubElement(seq, "media", {"src": _rel_or_abs(t.path, target, relative)})
        ET.indent(root)
        text = '<?wpl version="1.0"?>\n' + ET.tostring(root, encoding="unicode") + "\n"
    elif ext == ".xspf":
        ns = "http://xspf.org/ns/0/"
        root = ET.Element("playlist", {"version": "1", "xmlns": ns})
        ET.SubElement(root, "title").text = name
        ET.SubElement(root, "creator").text = "Triple 9 Music Player"
        tl = ET.SubElement(root, "trackList")
        for t in tracks:
            node = ET.SubElement(tl, "track")
            ET.SubElement(node, "location").text = "file:///" + t.path.replace("\\", "/").replace(" ", "%20")
            ET.SubElement(node, "title").text = t.title
            ET.SubElement(node, "creator").text = t.display_artist
            if t.album:
                ET.SubElement(node, "album").text = t.album
            if t.duration:
                ET.SubElement(node, "duration").text = str(int(t.duration * 1000))
        ET.indent(root)
        text = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"
    else:
        lines = ["#EXTM3U", f"#PLAYLIST:{name}"]
        for t in tracks:
            lines.append(f"#EXTINF:{int(round(t.duration))},{t.display_artist} - {t.title}")
            if t.album:
                lines.append(f"#EXTALB:{t.album}")
            lines.append(_rel_or_abs(t.path, target, relative))
        text = "\n".join(lines) + "\n"
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    os.replace(tmp, target)


def safe_file_name(name):
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", name).strip(" .")
    return clean[:80] or "playlist"
