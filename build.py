"""Build T9 Music Player: standalone .exe + Windows installer.

    python build.py              build everything, ask whether to publish
    python build.py --publish    also copy the installer into the update folder
    python build.py --no-publish never ask

Steps
  1. a clean virtual environment in build\\venv (only the player's packages,
     so nothing else installed on this computer ends up in the program)
  2. unit tests
  3. PyInstaller -> dist\\T9 Music Player\\T9 Music Player.exe (no Python needed)
  4. self-test of the built exe (codecs, audio devices, lossless decoding, UI)
  5. Inno Setup -> dist\\T9MusicPlayer-Setup-X.Y.Z.exe
  6. optional: copy the installer into the update folder from the player's
     settings, so other computers offer the update on their next start

To release a new version: raise APP_VERSION in t9player/__init__.py, run this.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(ROOT, "build")
DIST = os.path.join(ROOT, "dist")
VENV = os.path.join(BUILD, "venv")
VPY = os.path.join(VENV, "Scripts", "python.exe")
APP = "T9 Music Player"


def step(text):
    print(f"\n=== {text} ===", flush=True)


def run(cmd, **kw):
    print("  > " + " ".join(f'"{c}"' if " " in c else c for c in cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


def version():
    with open(os.path.join(ROOT, "t9player", "__init__.py"), encoding="utf-8") as handle:
        m = re.search(r'APP_VERSION\s*=\s*"(\d+\.\d+\.\d+)"', handle.read())
    if not m:
        sys.exit("APP_VERSION not found in t9player/__init__.py")
    return m.group(1)


def make_venv():
    step("1/6  Clean build environment")
    if sys.version_info < (3, 10) or sys.maxsize < 2 ** 32:
        sys.exit("Use 64-bit Python 3.10 or newer to build.")
    if not os.path.isfile(VPY):
        run([sys.executable, "-m", "venv", VENV])
    run([VPY, "-m", "pip", "install", "--disable-pip-version-check", "-q", "--upgrade", "pip"])
    run([VPY, "-m", "pip", "install", "--disable-pip-version-check", "-q",
         "-r", os.path.join(ROOT, "requirements.txt"), "pyinstaller>=6.3"])


def unit_tests():
    step("2/6  Unit tests")
    run([VPY, "-m", "unittest", "discover", "-s", "tests"], cwd=ROOT)


VERSION_FILE = """VSVersionInfo(
  ffi=FixedFileInfo(filevers=({a}, {b}, {c}, 0), prodvers=({a}, {b}, {c}, 0), mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Triplenine'),
      StringStruct('FileDescription', '{app}'),
      StringStruct('FileVersion', '{v}'),
      StringStruct('InternalName', '{app}'),
      StringStruct('OriginalFilename', '{app}.exe'),
      StringStruct('ProductName', '{app}'),
      StringStruct('ProductVersion', '{v}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def pyinstaller(ver):
    step("3/6  Standalone program (PyInstaller)")
    os.makedirs(BUILD, exist_ok=True)
    a, b, c = ver.split(".")
    vfile = os.path.join(BUILD, "version_info.txt")
    with open(vfile, "w", encoding="utf-8") as handle:
        handle.write(VERSION_FILE.format(a=a, b=b, c=c, v=ver, app=APP))
    out = os.path.join(DIST, APP)
    if os.path.isdir(out):
        shutil.rmtree(out)
    run([VPY, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
         "--name", APP,
         "--icon", os.path.join(ROOT, "assets", "t9.ico"),
         "--add-data", f"{os.path.join(ROOT, 'assets')}{os.pathsep}assets",
         "--version-file", vfile,
         "--exclude-module", "tkinter",
         "--distpath", DIST,
         "--workpath", os.path.join(BUILD, "pyinstaller"),
         "--specpath", BUILD,
         os.path.join(ROOT, f"{APP}.pyw")], cwd=ROOT)
    exe = os.path.join(out, f"{APP}.exe")
    if not os.path.isfile(exe):
        sys.exit("PyInstaller did not produce the exe")
    size = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(out) for f in fs)
    print(f"  {exe}  ({size / 1048576:.0f} MB)")
    return exe


def selftest(exe):
    step("4/6  Self-test of the built program")
    report_dir = tempfile.mkdtemp(prefix="t9_selftest_")
    env = dict(os.environ, T9_SELFTEST=report_dir, T9_PLAYER_DATA=os.path.join(report_dir, "data"))
    proc = subprocess.Popen([exe], env=env)
    try:
        code = proc.wait(timeout=90)
    except subprocess.TimeoutExpired:
        proc.kill()
        sys.exit("Self-test timed out - the exe did not finish starting")
    report_file = os.path.join(report_dir, "report.json")
    if not os.path.isfile(report_file):
        log = os.path.join(report_dir, "data", "logs", "t9player.log")
        tail = open(log, encoding="utf-8", errors="replace").read()[-3000:] if os.path.isfile(log) else ""
        sys.exit(f"Self-test produced no report (exit code {code}).\n{tail}")
    with open(report_file, encoding="utf-8") as handle:
        report = json.load(handle)
    for name, ok in report["checks"].items():
        print(f"  {'OK  ' if ok else 'FAIL'}  {name}")
    for err in report["errors"]:
        print("  " + err)
    if not report.get("ok"):
        sys.exit("Self-test failed - see above")
    shutil.copy(os.path.join(report_dir, "selftest.png"), os.path.join(BUILD, "selftest.png"))
    print(f"  screenshot: {os.path.join(BUILD, 'selftest.png')}")


def find_iscc():
    candidates = [
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Inno Setup 6", "ISCC.exe"),
        os.path.join(os.environ.get("ProgramFiles", ""), "Inno Setup 6", "ISCC.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Inno Setup 6", "ISCC.exe"),
    ]
    found = shutil.which("ISCC")
    if found:
        return found
    return next((c for c in candidates if os.path.isfile(c)), None)


def installer(ver):
    step("5/6  Installer (Inno Setup)")
    iscc = find_iscc()
    if iscc is None:
        print("  Inno Setup 6 is not installed - installing it with winget (free, jrsoftware.org)...")
        try:
            run(["winget", "install", "--id", "JRSoftware.InnoSetup", "-e", "--scope", "user",
                 "--accept-package-agreements", "--accept-source-agreements"])
        except (OSError, subprocess.CalledProcessError):
            pass
        time.sleep(1)
        iscc = find_iscc()
    if iscc is None:
        sys.exit("Inno Setup 6 is needed for the installer: https://jrsoftware.org/isdl.php\n"
                 f"The standalone program is ready anyway in {os.path.join(DIST, APP)}")
    run([iscc, "/Q", f"/DAppVersion={ver}", os.path.join(ROOT, "installer", "T9MusicPlayer.iss")])
    setup = os.path.join(DIST, f"T9MusicPlayer-Setup-{ver}.exe")
    if not os.path.isfile(setup):
        sys.exit("Inno Setup did not produce the installer")
    print(f"  {setup}  ({os.path.getsize(setup) / 1048576:.0f} MB)")
    # the same file under the fixed name that is attached to the GitHub release
    release_copy = os.path.join(DIST, "Triple9MusicPlayer-Setup.exe")
    shutil.copy2(setup, release_copy)
    print(f"  {release_copy}  <- attach this one to the GitHub release (tag v{ver})")
    return setup


def publish(setup, mode):
    step("6/6  Publish to the update folder")
    settings_file = os.path.join(os.environ.get("APPDATA", ""), APP, "settings.json")
    folder = ""
    try:
        with open(settings_file, encoding="utf-8") as handle:
            folder = json.load(handle).get("update_folder", "")
    except (OSError, ValueError):
        pass
    if not folder or not os.path.isdir(folder):
        print("  No update folder set in the player (Settings > General > Updates) - skipped.")
        return
    if mode == "ask":
        if not sys.stdin.isatty():
            print("  Not interactive - skipped (use --publish).")
            return
        answer = input(f"  Copy the installer to {folder} so other computers update? [Y/n] ").strip().lower()
        if answer not in ("", "y", "yes", "t", "tak"):
            print("  Skipped.")
            return
    elif mode == "no":
        print("  Skipped (--no-publish).")
        return
    shutil.copy2(setup, folder)
    print(f"  Copied to {folder}")


def main():
    mode = "yes" if "--publish" in sys.argv else "no" if "--no-publish" in sys.argv else "ask"
    ver = version()
    print(f"Building {APP} {ver}")
    make_venv()
    unit_tests()
    exe = pyinstaller(ver)
    selftest(exe)
    setup = installer(ver)
    publish(setup, mode)
    print(f"\nDone: {setup}")


if __name__ == "__main__":
    main()
