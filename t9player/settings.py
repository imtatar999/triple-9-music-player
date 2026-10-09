"""JSON settings with defaults, validation and atomic saving."""

import json
import os
import threading

from . import paths

DEFAULTS = {
    # Playback
    "output_device": "",            # WASAPI device name, "" = system default
    "exclusive_mode": False,        # WASAPI exclusive = bit-perfect
    "buffer_ms": 150,
    "gapless": True,
    "crossfade": 0,                 # seconds of overlap between songs, 0 = off (bit-perfect)
    "resume_on_start": True,
    "volume": 0.8,
    "muted": False,
    "shuffle": False,
    "repeat": "off",                # off | all | one
    # Lyrics
    "lyrics_font_size": 30,
    "lyrics_font_family": "Segoe UI",
    "lyrics_bold": True,
    "lyrics_align": "left",         # left | center
    "lyrics_active_color": "#ffffff",
    "lyrics_upcoming_color": "#d9a3a8",
    "lyrics_past_color": "#6e4a4f",
    "lyrics_cover_side": "left",    # left | right
    "lyrics_blur_background": True,
    "lyrics_karaoke": True,         # word-by-word fill for enhanced LRC
    "lyrics_order": ["embedded", "lrc", "txt"],   # where to look for lyrics first
    # Look
    "theme": "999",
    "unlocked_themes": [],          # before 1.4 (no longer used)
    "theme_keys": {},               # secret theme -> key derived from its code (see vault.py)
    "language": "auto",             # auto | en | pl
    "matrix_rain": True,            # falling code animation in the Matrix theme
    # Library
    "library_folders": [],
    "online_covers": True,          # official album covers from MusicBrainz
    "album_covers": {},             # album key -> {"source": "songs"|"track"|"file", "path": ...}
    "artist_pictures": {},          # artist key -> {"source": "track"|"file", "path": ...}
    "list_density": "list",         # list | compact
    "list_sort": {},                # view -> [sort key, descending]
    "rescan_on_start": True,
    # Window
    "minimize_to_tray": False,
    "global_media_keys": True,
    "online_updates": True,         # look for a newer release on GitHub at start-up
    "update_folder": "",            # folder that receives new T9MusicPlayer-Setup-X.Y.Z.exe files
    "mini_on_top": True,
    "window_geometry": "",
    "mini_geometry": "",
}

_VALIDATORS = {
    "buffer_ms": lambda v: isinstance(v, int) and 40 <= v <= 1000,
    "volume": lambda v: isinstance(v, (int, float)) and 0.0 <= v <= 1.0,
    "repeat": lambda v: v in ("off", "all", "one"),
    "lyrics_font_size": lambda v: isinstance(v, int) and 10 <= v <= 120,
    "lyrics_align": lambda v: v in ("left", "center"),
    "lyrics_cover_side": lambda v: v in ("left", "right"),
    "library_folders": lambda v: isinstance(v, list) and all(isinstance(x, str) for x in v),
    "lyrics_order": lambda v: isinstance(v, list) and all(x in ("embedded", "lrc", "txt") for x in v),
    "crossfade": lambda v: isinstance(v, int) and 0 <= v <= 12,
    "language": lambda v: v in ("auto", "en", "pl"),
    "list_density": lambda v: v in ("list", "compact"),
    "unlocked_themes": lambda v: isinstance(v, list) and all(isinstance(x, str) for x in v),
    "theme_keys": lambda v: isinstance(v, dict) and all(isinstance(k, str) and isinstance(x, str)
                                                        for k, x in v.items()),
    "album_covers": lambda v: isinstance(v, dict),
    "artist_pictures": lambda v: isinstance(v, dict),
    "list_sort": lambda v: isinstance(v, dict),
}


def _valid(key, value):
    default = DEFAULTS[key]
    check = _VALIDATORS.get(key)
    if check is not None:
        return check(value)
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, (int, float)) and not isinstance(default, bool):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, type(default))


def read_json(path, fallback):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, type(fallback)) else fallback
    except (OSError, ValueError):
        return fallback


def write_json_atomic(path, data):
    """Write to a temp file first so a crash never leaves half a file."""
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


class Settings:
    def __init__(self, path=None):
        self.path = path or paths.SETTINGS_FILE
        self._lock = threading.Lock()
        self._data = dict(DEFAULTS)
        stored = read_json(self.path, {})
        for key, value in stored.items():
            if key in DEFAULTS and _valid(key, value):
                self._data[key] = value

    def get(self, key):
        with self._lock:
            return self._data.get(key, DEFAULTS.get(key))

    def set(self, key, value, save=True):
        if key in DEFAULTS and not _valid(key, value):
            return
        with self._lock:
            self._data[key] = value
        if save:
            self.save()

    def update(self, values):
        for key, value in values.items():
            self.set(key, value, save=False)
        self.save()

    def save(self):
        with self._lock:
            snapshot = dict(self._data)
        return write_json_atomic(self.path, snapshot)

    def __getitem__(self, key):
        return self.get(key)
