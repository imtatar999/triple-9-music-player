"""Locations of the program's assets and per-user data."""

import os
import sys

FROZEN = bool(getattr(sys, "frozen", False))
if FROZEN:
    # PyInstaller build: bundled files live next to the exe in _internal (sys._MEIPASS)
    PROGRAM_DIR = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    EXE_DIR = os.path.dirname(sys.executable)
else:
    PROGRAM_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    EXE_DIR = PROGRAM_DIR
ASSETS_DIR = os.path.join(PROGRAM_DIR, "assets")
ICON_FILE = os.path.join(ASSETS_DIR, "t9.ico")
LOGO_FILE = os.path.join(ASSETS_DIR, "t9.png")


def _data_root():
    override = os.environ.get("T9_PLAYER_DATA")
    if override:
        return override
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "T9 Music Player")


DATA_DIR = _data_root()
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
SESSION_FILE = os.path.join(DATA_DIR, "session.json")
LIBRARY_DB = os.path.join(DATA_DIR, "library.db")
THUMB_DIR = os.path.join(DATA_DIR, "thumbs")
LOG_DIR = os.path.join(DATA_DIR, "logs")


def ensure_dirs():
    for path in (DATA_DIR, THUMB_DIR, LOG_DIR):
        try:
            os.makedirs(path, exist_ok=True)
        except OSError:
            pass


def default_music_dir():
    home = os.path.expanduser("~")
    for name in ("Music", "Muzyka"):
        path = os.path.join(home, name)
        if os.path.isdir(path):
            return path
    return home


IS_WINDOWS = sys.platform.startswith("win")
