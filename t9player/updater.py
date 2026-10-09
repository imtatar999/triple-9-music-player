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


def check_github(current=APP_VERSION, timeout=8):
    """(version_text, download_url) of a newer installer in the latest GitHub release, else None.

    Only reads public release information - nothing about this computer is sent."""
    import json
    import urllib.request
    req = urllib.request.Request(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
                                 headers={"Accept": "application/vnd.github+json",
                                          "User-Agent": "Triple9MusicPlayer-updater"})
    import urllib.error
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:          # no release published yet
            return None
        raise
    best = None
    for asset in data.get("assets", []):
        m = SETUP_RE.match(asset.get("name", ""))
        if m and asset.get("browser_download_url", "").startswith("https://"):
            version = tuple(int(x) for x in m.groups())
            if best is None or version > best[0]:
                best = (version, asset["browser_download_url"], int(asset.get("size") or 0))
    if best is None or best[0] <= parse_version(current):
        return None
    return ".".join(map(str, best[0])), best[1], best[2]


def download(url, size_hint=0, progress=None, timeout=20):
    """Download an installer into the temp folder; returns its path. progress(done, total) is optional."""
    import tempfile
    import urllib.request
    name = url.rsplit("/", 1)[-1]
    if not SETUP_RE.match(name):
        raise ValueError("unexpected file name")
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
