"""Updates: from the project's GitHub releases (online) and/or from a folder.

Online: a newer T9MusicPlayer-Setup-X.Y.Z.exe attached to the latest GitHub release is offered
at start-up, downloaded and installed. Folder: put a newer installer in the folder chosen in
Settings (OneDrive, a USB stick, a network share...) and every computer that uses it offers it.

The installer upgrades the program in place; the library, playlists and settings
live in %APPDATA% and are never touched by an update.
"""

import os
import re
import subprocess

from . import APP_VERSION

SETUP_RE = re.compile(r"^T9MusicPlayer-Setup-(\d+)\.(\d+)\.(\d+)\.exe$", re.IGNORECASE)


def parse_version(text):
    m = re.match(r"^\s*(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def find_update(folder, current=APP_VERSION):
    """(version_text, installer_path) of the newest installer newer than `current`, else None."""
    if not folder or not os.path.isdir(folder):
        return None
    best = None
    try:
        names = os.listdir(folder)
    except OSError:
        return None
    for name in names:
        m = SETUP_RE.match(name)
        if not m:
            continue
        version = tuple(int(x) for x in m.groups())
        if best is None or version > best[0]:
            best = (version, os.path.join(folder, name))
    if best is None or best[0] <= parse_version(current):
        return None
    return ".".join(map(str, best[0])), best[1]


def launch_installer(path):
    """Start the installer quietly. It closes the player, upgrades it and starts it again."""
    flags = 0x00000008 | 0x00000200 if os.name == "nt" else 0   # DETACHED_PROCESS | NEW_PROCESS_GROUP
    subprocess.Popen([path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
                     close_fds=True, creationflags=flags)


# --------------------------------------------------------------------------- GitHub releases

GITHUB_REPO = "imtatar999/triple-9-music-player"
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases"


# the installer attached to every release has this fixed name, so the page can always link to
# .../releases/latest/download/Triple9MusicPlayer-Setup.exe; the version comes from the release tag
SETUP_NAME = "Triple9MusicPlayer-Setup.exe"
LATEST_DOWNLOAD = f"https://github.com/{GITHUB_REPO}/releases/latest/download/{SETUP_NAME}"


def check_github(current=APP_VERSION, timeout=8):
    """(version_text, download_url, size, release_notes) when the latest GitHub release is newer, else None.

    Only reads public release information - nothing about this computer is sent."""
    import json
    import urllib.error
    import urllib.request
    req = urllib.request.Request(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
                                 headers={"Accept": "application/vnd.github+json",
                                          "User-Agent": "Triple9MusicPlayer-updater"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:          # no release published yet
            return None
        raise
    version = parse_version(data.get("tag_name", "").lstrip("vV"))
    asset = None
    for item in data.get("assets", []):
        name = item.get("name", "")
        if not item.get("browser_download_url", "").startswith("https://"):
            continue
        if name.lower() == SETUP_NAME.lower():
            asset = item
            break
        m = SETUP_RE.match(name)
        if m and tuple(int(x) for x in m.groups()) == version:
            asset = item             # older releases: T9MusicPlayer-Setup-X.Y.Z.exe
    if asset is None or version <= parse_version(current):
        return None
    notes = (data.get("body") or "").strip()
    return ".".join(map(str, version)), asset["browser_download_url"], int(asset.get("size") or 0), notes


def download(url, size_hint=0, progress=None, timeout=20, version=""):
    """Download an installer into the temp folder; returns its path. progress(done, total) is optional."""
    import tempfile
    import urllib.request
    name = url.rsplit("/", 1)[-1]
    if not (SETUP_RE.match(name) or name.lower() == SETUP_NAME.lower()):
        raise ValueError("unexpected file name")
    if version:
        name = f"T9MusicPlayer-Setup-{version}.exe"
    target = os.path.join(tempfile.gettempdir(), name)
    part = target + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": "Triple9MusicPlayer-updater"})
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(part, "wb") as out:
        total = int(resp.headers.get("Content-Length") or size_hint or 0)
        done = 0
        while True:
            chunk = resp.read(256 * 1024)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    if total and os.path.getsize(part) != total:
        os.remove(part)
        raise OSError("the download was interrupted")
    os.replace(part, target)
    return target
