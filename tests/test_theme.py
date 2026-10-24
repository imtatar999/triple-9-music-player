import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from t9player import pack, theme  # noqa: E402

PAYLOAD = {"name": "testpack", "theme": dict(theme.THEMES["999"], label="Test", hint="x"),
           "phrases": {"Nothing playing": "Shh"}, "extras": {"notes": ["hi"]}, "pl": {}, "files": {}}


class ThemeTests(unittest.TestCase):
    def setUp(self):
        self.pack = pack.seal([("open sesame", PAYLOAD)], iterations=1000)
        theme._pack = self.pack

    def tearDown(self):
        theme._pack = None
        theme.THEMES.pop("testpack", None)

    def test_public_order(self):
        self.assertEqual(theme.visible_themes({}), ["999", "gbgr", "wod", "drfl", "lnd", "tpne", "outsiders"])

    def test_same_code_shows_and_hides(self):
        name, shown, keys = theme.try_code("  Open Sesame ", {})
        self.assertEqual((name, shown), ("testpack", True))
        self.assertEqual(theme.visible_themes(keys)[-1], "testpack")
        name, shown, keys = theme.try_code("open sesame", keys)
        self.assertEqual((name, shown, keys), ("testpack", False, {}))
        self.assertEqual(theme.try_code("wrong", {"a": "b"}), (None, False, {"a": "b"}))

    def test_saved_keys_reopen_and_forged_keys_do_not(self):
        key, _ = pack.open_with_code("open sesame", self.pack)
        self.assertEqual(theme.open_saved({"testpack": key, "other": "00" * 64}), {"testpack": key})

    def test_pack_hides_everything(self):
        raw = str(self.pack)
        for word in ("testpack", "Shh", "open sesame"):
            self.assertNotIn(word, raw)

    def test_every_theme_is_complete(self):
        keys = set(theme.THEMES["999"])
        for name, values in theme.THEMES.items():
            self.assertEqual(set(values), keys, name)
            self.assertTrue(os.path.isfile(os.path.join(os.path.dirname(theme.__file__), "..", "assets",
                                                        "logos", values["LOGO"] + ".png")), name)

    def test_title_case(self):
        self.assertEqual(theme.title_text("Najczęściej", "lower_ascii"), "najczesciej")
        self.assertEqual(theme.title_text("Abc", "upper"), "ABC")

    def test_decorative_fonts_without_polish_letters(self):
        self.assertEqual(theme.title_text("ZAŻÓŁĆ GĘŚLĄ", "none", "Old London"), "ZAZOLC GESLĄ".replace("Ą", "A"))
        self.assertEqual(theme.title_text("Dzień dobry", "none", "Segoe UI"), "Dzień dobry")


if __name__ == "__main__":
    unittest.main()
