#!/bin/bash
# Build the macOS app: dist/Triple 9 Music Player.app + dist/Triple9MusicPlayer-macOS.dmg
# Run on a Mac with Python 3.10+:   ./build_mac.sh
# The app is NOT notarized (no paid Apple Developer ID): first start = right-click > Open.
set -euo pipefail
cd "$(dirname "$0")"
APP="T9 Music Player"
VER=$(sed -n 's/.*APP_VERSION *= *"\([0-9.]*\)".*/\1/p' t9player/__init__.py | head -1)
PY=${PYTHON:-python3}
echo "=== Triple 9 Music Player $VER for macOS ($(uname -m)) ==="

echo "=== 1/5 clean build environment ==="
[ -x build/venv/bin/python ] || "$PY" -m venv build/venv
build/venv/bin/pip install -q --upgrade pip
build/venv/bin/pip install -q -r requirements.txt "pyinstaller>=6.3"

echo "=== 2/5 unit tests ==="
build/venv/bin/python -m unittest discover -s tests -q

echo "=== 3/5 PyInstaller ==="
# icon from the PNG
ICONSET=build/t9.iconset; rm -rf "$ICONSET"; mkdir -p "$ICONSET"
for s in 16 32 128 256 512; do sips -z $s $s assets/t9.png --out "$ICONSET/icon_${s}x${s}.png" >/dev/null; done
sips -z 64 64 assets/t9.png --out "$ICONSET/icon_32x32@2x.png" >/dev/null
sips -z 256 256 assets/t9.png --out "$ICONSET/icon_128x128@2x.png" >/dev/null
sips -z 512 512 assets/t9.png --out "$ICONSET/icon_256x256@2x.png" >/dev/null
cp "$ICONSET/icon_32x32.png" "$ICONSET/icon_16x16@2x.png"
iconutil -c icns "$ICONSET" -o build/t9.icns
rm -rf "dist/$APP.app" "dist/$APP"
build/venv/bin/python -m PyInstaller --noconfirm --clean --windowed \
    --name "$APP" --icon "$PWD/build/t9.icns" \
    --osx-bundle-identifier com.triplenine.t9musicplayer \
    --add-data "$PWD/assets:assets" --exclude-module tkinter \
    --distpath dist --workpath build/pyinstaller --specpath build \
    "$APP.pyw"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VER" -c "Set :CFBundleVersion $VER" \
    -c "Set :CFBundleDisplayName Triple 9 Music Player" "dist/$APP.app/Contents/Info.plist" 2>/dev/null || true
codesign --force --deep -s - "dist/$APP.app"

echo "=== 4/5 self-test of the built app ==="
REPORT=$(mktemp -d)
T9_SELFTEST="$REPORT" T9_PLAYER_DATA="$REPORT/data" "dist/$APP.app/Contents/MacOS/$APP" || true
[ -f "$REPORT/report.json" ] || { echo "Self-test produced no report"; tail -30 "$REPORT/data/logs/t9player.log" 2>/dev/null; exit 1; }
build/venv/bin/python - "$REPORT/report.json" <<'PYEOF'
import json, sys
r = json.load(open(sys.argv[1]))
for k, ok in r["checks"].items(): print("  %s  %s" % ("OK  " if ok else "FAIL", k))
for e in r["errors"]: print("  " + e)
sys.exit(0 if r.get("ok") else "Self-test failed")
PYEOF
cp "$REPORT/selftest.png" build/selftest_mac.png

echo "=== 5/5 disk image ==="
DMG="dist/Triple9MusicPlayer-macOS.dmg"
STAGE=$(mktemp -d); cp -R "dist/$APP.app" "$STAGE/"; ln -s /Applications "$STAGE/Applications"
rm -f "$DMG"
hdiutil create -volname "Triple 9 Music Player" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
cp "$DMG" "dist/T9MusicPlayer-macOS-$VER.dmg"
echo "Done: $DMG ($(du -h "$DMG" | cut -f1))"
