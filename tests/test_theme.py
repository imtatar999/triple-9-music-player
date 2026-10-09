import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from t9player import theme, vault  # noqa: E402

PAYLOAD = {"name": "testsecret", "theme": dict(theme.THEMES["999"], label="Test", hint="x"),
           "phrases": {"Nothing playing": "Shh"}, "extras": {"notes": ["hi"]}, "pl": {}, "files": {}}


class ThemeTests(unittest.TestCase):
    def setUp(self):
        self.vault = vault.seal([("open sesame", PAYLOAD)], iterations=1000)
        theme._vault = self.vault

    def tearDown(self):
        theme._vault = None
        theme.THEMES.pop("testsecret", None)

    def test_public_order(self):
        self.assertEqual(theme.visible_themes({}), ["999", "gbgr", "wod", "drfl", "lnd", "tpne", "outsiders"])

    def test_same_code_shows_and_hides(self):
        name, shown, keys = theme.try_code("  Open Sesame ", {})
        self.assertEqual((name, shown), ("testsecret", True))
        self.assertEqual(theme.visible_themes(keys)[-1], "testsecret")
        name, shown, keys = theme.try_code("open sesame", keys)
        self.assertEqual((name, shown, keys), ("testsecret", False, {}))
        self.assertEqual(theme.try_code("wrong", {"a": "b"}), (None, False, {"a": "b"}))

    def test_saved_keys_reopen_and_forged_keys_do_not(self):
        key, _ = vault.unlock("open sesame", self.vault)
        self.assertEqual(theme.open_saved({"testsecret": key, "other": "00" * 64}), {"testsecret": key})

    def test_vault_hides_everything(self):
        raw = str(self.vault)
        for word in ("testsecret", "Shh", "open sesame"):
            self.assertNotIn(word, raw)

    def test_source_has_no_codes_or_secret_texts(self):
        root = os.path.dirname(theme.__file__)
        for folder, _, files in os.walk(root):
            for name in files:
                if name.endswith(".py"):
                    text = open(os.path.join(folder, name), encoding="utf-8").read().lower()
                    for word in ("_secrets", "code_hash", "love_notes"):
                        self.assertNotIn(word, text, name)

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
