"""Double-click to start T9 Music Player (no console window)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from t9player.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
