"""Every English UI text has a Polish translation (and the placeholders match)."""

import ast
import os
import string
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from t9player import i18n, meta, theme  # noqa: E402
from t9player.i18n_pl import PL  # noqa: E402


def literal_keys():
    """Strings passed directly to tr("...")."""
    keys = set()
    for folder, _, files in os.walk(os.path.join(ROOT, "t9player")):
        for name in files:
            if not name.endswith(".py"):
                continue
            with open(os.path.join(folder, name), encoding="utf-8") as handle:
                tree = ast.parse(handle.read())
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tr"
                        and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                    keys.add(node.args[0].value)
    return keys


def table_keys():
    """Texts translated through variables: menus, columns, theme hints ..."""
    from t9player.ui import home_page, library_view, main_window
    keys = set()
    for _, label, _, tip in main_window.NAV_ITEMS:
        keys.update((label, tip))
    keys.update(label for _, label, _, _ in library_view.SORT_OPTIONS)
    keys.update(c for c in library_view.COLUMNS if c != "#")
    keys.update(label for _, label in i18n.LANGUAGES)
    keys.update(t["hint"] for t in theme.THEMES.values())
    keys.update(meta.LYRICS_SOURCE_NAMES.values())
    keys.update(s for pair in home_page.ABOUT.values() for s in pair)
    keys.update(("Compact", "List", "Title", "Artist", "Album", "Album artist", "Year", "Genre", "Track / disc",
                 "Duration", "Format", "Sample rate", "Bit depth", "Channels", "Bitrate", "File size", "Plays",
                 "Lyrics", "File"))
    return keys


def fields(text):
    return {f for _, f, _, _ in string.Formatter().parse(text) if f}


class I18nTests(unittest.TestCase):
    def test_everything_translated(self):
        keys = literal_keys() | table_keys()
        missing = sorted(k for k in keys if k not in PL)
        self.assertEqual(missing, [], "texts without a Polish translation")

    def test_placeholders_match(self):
        for en, pl in PL.items():
            self.assertEqual(fields(en), fields(pl), f"placeholders differ: {en!r}")

    def test_plural(self):
        i18n.set_language("pl")
        try:
            self.assertEqual(i18n.songs(1), "1 utwór")
            self.assertEqual(i18n.songs(3), "3 utwory")
            self.assertEqual(i18n.songs(5), "5 utworów")
            self.assertEqual(i18n.songs(22), "22 utwory")
            self.assertEqual(i18n.songs(12), "12 utworów")
            self.assertEqual(i18n.tr("Albums"), "Albumy")
        finally:
            i18n.set_language("en")
        self.assertEqual(i18n.songs(1), "1 song")
        self.assertEqual(i18n.tr("Albums"), "Albums")


if __name__ == "__main__":
    if "--list-missing" in sys.argv:
        keys = literal_keys() | table_keys()
        for k in sorted(k for k in keys if k not in PL):
            print(repr(k))
    else:
        unittest.main()
