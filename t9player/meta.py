"""Reading tags, technical info, cover art and lyrics from audio files.

Every public function here is defensive: a broken or exotic file returns
partial data or None, it never raises.
"""

import base64
import os
import re
import threading

from . import lyrics as lyr

AUDIO_EXTS = {
    ".mp3", ".flac", ".wav", ".wave", ".m4a", ".m4b", ".mp4", ".aac", ".alac",
    ".ogg", ".oga", ".opus", ".wma", ".aif", ".aiff", ".aifc", ".ape", ".wv",
    ".dsf", ".dff", ".mka", ".webm", ".tta", ".mpc", ".ac3", ".caf", ".w64",
}
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
COVER_NAMES = ("cover", "folder", "front", "album", "albumart", "albumartlarge", "art", "artwork")
LYRICS_SUBDIRS = ("SYNCED LYRICS", "Synced Lyrics", "LRC", "Lyrics", "LYRICS", "lyrics")
LOSSLESS_CODECS = {"FLAC", "ALAC", "WAV", "AIFF", "APE", "WavPack", "TTA", "DSD", "W64", "CAF"}


def is_audio(path):
    return os.path.splitext(path)[1].lower() in AUDIO_EXTS


# --------------------------------------------------------------------------- tags

def _text(value):
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    if hasattr(value, "text") and not isinstance(value, str):     # ID3 frame
        return _text(value.text)
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", errors="replace").strip("\x00 ")
        except Exception:
            return ""
    return str(value).strip("\x00 ").strip()


def _number(value):
    """'3/12' -> 3, (3, 12) -> 3, '' -> 0."""
    if isinstance(value, (list, tuple)) and value:
        value = value[0]
    if isinstance(value, tuple):
        value = value[0]
    m = re.match(r"\s*(\d+)", _text(value) if not isinstance(value, int) else str(value))
    return int(m.group(1)) if m else 0


def _year(value):
    m = re.search(r"(\d{4})", _text(value))
    return m.group(1) if m else ""


_GENERIC_KEYS = {
    "title": ("title", "©nam", "tit2"),
    "artist": ("artist", "author", "©art", "tpe1"),
    "album": ("album", "wm/albumtitle", "©alb", "talb"),
    "albumartist": ("albumartist", "album artist", "album_artist", "wm/albumartist", "aart", "tpe2"),
    "date": ("date", "year", "originaldate", "wm/year", "©day", "tdrc", "tyer"),
    "track": ("tracknumber", "track", "wm/tracknumber", "trkn", "trck"),
    "disc": ("discnumber", "disc", "disk", "wm/partofset", "tpos"),
    "genre": ("genre", "wm/genre", "©gen", "tcon"),
}


def _tags_to_dict(tags):
    """Flatten any mutagen tag container into a lowercase-key dict of raw values."""
    flat = {}
    if tags is None:
        return flat
    try:
        items = list(tags.items())
    except Exception:
        return flat
    for key, value in items:
        k = str(key).lower()
        if ":" in k and len(k) > 4 and k[4] == ":":    # ID3 'TXXX:foo', 'USLT::eng'
            base = k[:4]
            flat.setdefault(base, value)
            flat.setdefault(k, value)
            if base == "txxx":
                flat.setdefault(k[5:], value)
        else:
            flat.setdefault(k, value)
    return flat


def read_tags(path):
    """Return a dict describing the track. Always returns something usable."""
    info = {
        "path": path, "title": "", "artist": "", "album": "", "albumartist": "",
        "year": "", "track": 0, "disc": 0, "genre": "", "duration": 0.0,
        "samplerate": 0, "bits": 0, "channels": 0, "bitrate": 0, "codec": "",
    }
    try:
        st = os.stat(path)
        info["mtime"] = st.st_mtime
        info["size"] = st.st_size
    except OSError:
        info["mtime"] = 0.0
        info["size"] = 0
    ok = False
    try:
        ok = _read_mutagen(path, info)
    except Exception:
        ok = False
    if not ok or info["duration"] <= 0 or not info["samplerate"]:
        try:
            _read_av(path, info)
        except Exception:
            pass
    stem = os.path.splitext(os.path.basename(path))[0].strip()
    if not info["title"]:
        info["title"] = stem
    if not info["codec"]:
        info["codec"] = os.path.splitext(path)[1].lstrip(".").upper()
    return info


def _codec_name(f, path):
    ext = os.path.splitext(path)[1].lower()
    name = type(f).__name__
    if name in ("MP3", "EasyMP3"):
        return "MP3"
    if name == "FLAC":
        return "FLAC"
    if name in ("MP4", "EasyMP4"):
        codec = str(getattr(f.info, "codec", "") or "").lower()
        return "ALAC" if "alac" in codec else "AAC"
    if name == "WAVE":
        return "WAV"
    if name == "AIFF":
        return "AIFF"
    if name == "OggOpus":
        return "Opus"
    if name in ("OggVorbis",):
        return "Vorbis"
    if name == "OggFLAC":
        return "FLAC"
    if name == "ASF":
        return "WMA"
    if name == "MonkeysAudio":
        return "APE"
    if name == "WavPack":
        return "WavPack"
    if name == "DSF" or ext in (".dsf", ".dff"):
        return "DSD"
    if name == "TrueAudio":
        return "TTA"
    if name == "Musepack":
        return "MPC"
    return ext.lstrip(".").upper()


def _read_mutagen(path, info):
    import mutagen
    f = mutagen.File(path)
    if f is None:
        return False
    i = f.info
    info["duration"] = float(getattr(i, "length", 0.0) or 0.0)
    info["samplerate"] = int(getattr(i, "sample_rate", 0) or 0)
    info["bits"] = int(getattr(i, "bits_per_sample", 0) or 0)
    info["channels"] = int(getattr(i, "channels", 0) or 0)
    info["bitrate"] = int(getattr(i, "bitrate", 0) or 0)
    info["codec"] = _codec_name(f, path)
    flat = _tags_to_dict(f.tags)
    for field_name, keys in _GENERIC_KEYS.items():
        for key in keys:
            if key in flat:
                raw = flat[key]
                if field_name in ("track", "disc"):
                    info[field_name] = _number(raw)
                elif field_name == "date":
                    info["year"] = _year(raw)
                else:
                    info[field_name] = _text(raw)
                if info.get(field_name if field_name != "date" else "year"):
                    break
    return True


def _read_av(path, info):
    import av
    with av.open(path, metadata_errors="ignore") as c:
        if not c.streams.audio:
            return
        s = c.streams.audio[0]
        cc = s.codec_context
        if c.duration and info["duration"] <= 0:
            info["duration"] = c.duration / 1_000_000.0
        elif s.duration and s.time_base and info["duration"] <= 0:
            info["duration"] = float(s.duration * s.time_base)
        info["samplerate"] = info["samplerate"] or int(cc.sample_rate or 0)
        info["channels"] = info["channels"] or int(cc.channels or 0)
        info["bitrate"] = info["bitrate"] or int(c.bit_rate or 0)
        if not info["codec"]:
            info["codec"] = cc.name.upper()
        meta = {k.lower(): v for k, v in dict(c.metadata).items()}
        meta.update({k.lower(): v for k, v in dict(s.metadata).items()})
        for field_name, keys in _GENERIC_KEYS.items():
            if field_name == "date":
                if not info["year"]:
                    for key in keys:
                        if meta.get(key):
                            info["year"] = _year(meta[key])
                            break
                continue
            if info.get(field_name):
                continue
            for key in keys:
                if meta.get(key):
                    info[field_name] = _number(meta[key]) if field_name in ("track", "disc") else _text(meta[key])
                    break


def format_label(codec, samplerate, bits, bitrate):
    """'FLAC 24/96', 'MP3 320k', 'ALAC 16/44.1'."""
    codec = codec or "?"
    if codec in LOSSLESS_CODECS and samplerate:
        khz = samplerate / 1000.0
        khz_txt = ("%g" % round(khz, 1))
        return f"{codec} {bits}/{khz_txt}" if bits else f"{codec} {khz_txt}k"
    if bitrate:
        return f"{codec} {int(round(bitrate / 1000.0))}k"
    return codec


def is_hires(samplerate, bits):
    return (bits or 0) > 16 or (samplerate or 0) > 48000


# --------------------------------------------------------------------------- folder index

class _DirIndex:
    """Caches directory listings: {normalised stem -> real filename}."""

    def __init__(self):
        self._lock = threading.Lock()
        self._cache = {}

    @staticmethod
    def norm(name):
        return re.sub(r"\s+", " ", name).strip().casefold()

    def listing(self, folder):
        try:
            mtime = os.stat(folder).st_mtime
        except OSError:
            return {}
        with self._lock:
            hit = self._cache.get(folder)
            if hit and hit[0] == mtime:
                return hit[1]
        entries = {}
        try:
            with os.scandir(folder) as it:
                for entry in it:
                    stem, ext = os.path.splitext(entry.name)
                    entries.setdefault((self.norm(stem), ext.lower()), entry.name)
                    entries.setdefault(("__name__", entry.name.casefold()), entry.name)
        except OSError:
            entries = {}
        with self._lock:
            if len(self._cache) > 512:
                self._cache.clear()
            self._cache[folder] = (mtime, entries)
        return entries

    def find(self, folder, stem, exts):
        listing = self.listing(folder)
        key = self.norm(stem)
        for ext in exts:
            name = listing.get((key, ext))
            if name:
                return os.path.join(folder, name)
        return None

    def subdir(self, folder, name):
        real = self.listing(folder).get(("__name__", name.casefold()))
        if real:
            path = os.path.join(folder, real)
            if os.path.isdir(path):
                return path
        return None


DIRS = _DirIndex()


# --------------------------------------------------------------------------- cover art

def _pick_picture(pictures):
    best = None
    for pic in pictures:
        ptype = getattr(pic, "type", 0)
        data = getattr(pic, "data", None)
        if not data:
            continue
        if ptype == 3:
            return data
        if best is None:
            best = data
    return best


def embedded_cover(path):
    """Bytes of the embedded front cover, or None."""
    try:
        import mutagen
        f = mutagen.File(path)
    except Exception:
        f = None
    if f is not None:
        try:
            data = _embedded_cover_mutagen(f)
            if data:
                return data
        except Exception:
            pass
    try:
        return _embedded_cover_av(path)
    except Exception:
        return None


def _embedded_cover_mutagen(f):
    pics = getattr(f, "pictures", None)          # FLAC
    if pics:
        data = _pick_picture(pics)
        if data:
            return data
    tags = f.tags
    if tags is None:
        return None
    name = type(tags).__name__
    if name == "ID3" or hasattr(tags, "getall"):
        return _pick_picture(tags.getall("APIC"))
    if name == "MP4Tags":
        covr = tags.get("covr")
        return bytes(covr[0]) if covr else None
    flat = _tags_to_dict(tags)
    block = flat.get("metadata_block_picture")
    if block:
        from mutagen.flac import Picture
        pictures = []
        for item in (block if isinstance(block, list) else [block]):
            try:
                pictures.append(Picture(base64.b64decode(_text(item) if not isinstance(item, bytes) else item)))
            except Exception:
                continue
        return _pick_picture(pictures)
    for key in ("cover art (front)", "cover art (other)"):     # APEv2
        if key in flat:
            raw = getattr(flat[key], "value", None)
            if isinstance(raw, bytes) and b"\x00" in raw:
                return raw.split(b"\x00", 1)[1]
    for key in ("wm/picture",):                               # ASF
        if key in flat:
            raw = flat[key]
            raw = raw[0] if isinstance(raw, list) else raw
            value = getattr(raw, "value", raw)
            if isinstance(value, bytes):
                return _parse_asf_picture(value)
    return None


def _parse_asf_picture(value):
    # type(1) size(4) mime(utf16z) description(utf16z) data
    try:
        pos = 5
        for _ in range(2):
            end = value.index(b"\x00\x00", pos)
            while (end - pos) % 2:
                end = value.index(b"\x00\x00", end + 1)
            pos = end + 2
        return value[pos:] or None
    except ValueError:
        return None


def _embedded_cover_av(path):
    import av
    with av.open(path, metadata_errors="ignore") as c:
        for s in c.streams.video:
            disp = getattr(s, "disposition", 0)
            if int(disp) & 0x400 or getattr(av.stream.Disposition, "attached_pic", 0) & int(disp):
                for packet in c.demux(s):
                    data = bytes(packet)
                    if data:
                        return data
                    break
    return None


def folder_cover_path(path):
    """Image file next to the track: '<track>.jpg', cover.jpg, folder.jpg ..."""
    folder = os.path.dirname(path)
    stem = os.path.splitext(os.path.basename(path))[0]
    hit = DIRS.find(folder, stem, IMAGE_EXTS)
    if hit:
        return hit
    for name in COVER_NAMES:
        hit = DIRS.find(folder, name, IMAGE_EXTS)
        if hit:
            return hit
    listing = DIRS.listing(folder)
    images = sorted(v for (k, ext), v in listing.items() if k != "__name__" and ext in IMAGE_EXTS)
    if len(images) == 1:
        return os.path.join(folder, images[0])
    for img in images:
        if "front" in img.casefold() or "cover" in img.casefold():
            return os.path.join(folder, img)
    return None


def cover_bytes(path):
    data = embedded_cover(path)
    if data:
        return data
    img = folder_cover_path(path)
    if img:
        try:
            with open(img, "rb") as handle:
                return handle.read()
        except OSError:
            return None
    return None


# --------------------------------------------------------------------------- lyrics

def _read_file_text(path):
    try:
        with open(path, "rb") as handle:
            data = handle.read(2_000_000)
        return lyr.decode_text_file(data)
    except OSError:
        return None


def sidecar_lyrics_path(path, exts=(".lrc",)):
    folder = os.path.dirname(path)
    stem = os.path.splitext(os.path.basename(path))[0]
    hit = DIRS.find(folder, stem, exts)
    if hit:
        return hit
    for sub in LYRICS_SUBDIRS:
        sub_path = DIRS.subdir(folder, sub)
        if sub_path:
            hit = DIRS.find(sub_path, stem, exts)
            if hit:
                return hit
    return None


def _embedded_lyrics(path):
    """(synced Lyrics | None, unsynced Lyrics | None)."""
    import mutagen
    f = mutagen.File(path)
    if f is None or f.tags is None:
        return None, None
    tags = f.tags
    synced = None
    texts = []
    if hasattr(tags, "getall"):                         # ID3
        for frame in tags.getall("SYLT"):
            if getattr(frame, "format", 2) == 2:
                synced = lyr.from_sylt(frame.text)
                if synced:
                    break
        for frame in tags.getall("USLT"):
            texts.append(("Embedded (USLT)", str(frame.text)))
        for frame in tags.getall("TXXX"):
            if str(frame.desc).lower() in ("lyrics", "syncedlyrics", "unsyncedlyrics"):
                texts.append(("Embedded (TXXX)", _text(frame.text)))
    else:
        flat = _tags_to_dict(tags)
        for key in ("syncedlyrics", "lyrics", "unsyncedlyrics", "unsynced lyrics", "©lyr", "wm/lyrics", "lyric"):
            if key in flat:
                raw = flat[key]
                value = getattr(raw[0] if isinstance(raw, list) and raw else raw, "value", None)
                value = value if isinstance(value, str) else _text(raw)
                texts.append((f"Embedded ({key.upper().lstrip('©')})", value))
    unsynced = None
    for label, text in texts:
        if not text or not text.strip():
            continue
        if lyr.looks_synced(text):
            if synced is None:
                parsed = lyr.parse_lrc(text, label)
                if parsed.synced and not parsed.is_empty():
                    synced = parsed
        elif unsynced is None:
            unsynced = lyr.plain_lyrics(text, label)
    return synced, unsynced


LYRICS_SOURCES = ("embedded", "lrc", "txt")
LYRICS_SOURCE_NAMES = {
    "embedded": "Embedded in the audio file (tags)",
    "lrc": ".lrc file next to the song / in a SYNCED LYRICS folder",
    "txt": ".txt file next to the song / in a LYRICS folder",
}


def normalize_lyrics_order(order):
    """Valid, complete source order; unknown names dropped, missing ones appended."""
    out = [s for s in (order or []) if s in LYRICS_SOURCES]
    out = list(dict.fromkeys(out))
    return out + [s for s in LYRICS_SOURCES if s not in out]


def _lyrics_from_source(path, source):
    """(synced, unsynced) found in one source; either may be None."""
    if source == "embedded":
        try:
            return _embedded_lyrics(path)
        except Exception:
            return None, None
    ext = ".lrc" if source == "lrc" else ".txt"
    side = sidecar_lyrics_path(path, (ext,))
    if not side:
        return None, None
    text = _read_file_text(side)
    parsed = lyr.parse_any(text, f"Sidecar {ext}", side) if text else None
    if parsed is None:
        return None, None
    return (parsed, None) if parsed.synced else (None, parsed)


def find_lyrics(path, order=None):
    """Best lyrics for a track.

    Sources are tried in `order` (default: embedded tags, .lrc, .txt). The first
    *synced* lyrics win; plain text is used only when no source has synced lyrics.
    """
    first_plain = None
    for source in normalize_lyrics_order(order):
        synced, plain = _lyrics_from_source(path, source)
        if synced is not None:
            return synced
        if first_plain is None and plain is not None:
            first_plain = plain
    return first_plain
