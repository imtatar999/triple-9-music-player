#!/bin/bash
# macOS: double-click in Finder to start Triple 9 Music Player from source
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
    echo "First start: installing the libraries (takes a minute)..."
    python3 -m venv .venv && .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -q -r requirements.txt || exit 1
fi
nohup .venv/bin/python "T9 Music Player.pyw" >/dev/null 2>&1 &
osascript -e 'tell application "Terminal" to close (every window whose name contains "Start T9 Music Player")' >/dev/null 2>&1 &
exit 0
