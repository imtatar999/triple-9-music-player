import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from t9player import updater  # noqa: E402

# the update file names differ per system (Windows installer / macOS disk image)
if updater.IS_MAC:
    def _setup(v):
        return f"T9MusicPlayer-macOS-{v}.dmg"
else:
    def _setup(v):
        return f"T9MusicPlayer-Setup-{v}.exe"


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="t9upd_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _touch(self, name):
        open(os.path.join(self.tmp, name), "wb").close()

    def test_picks_newest_newer_version(self):
        for name in (_setup("1.0.9"), _setup("1.2.0"),
                     _setup("1.10.0"), "notes.txt", _setup("x")):
            self._touch(name)
        version, path = updater.find_update(self.tmp, "1.1.0")
        self.assertEqual(version, "1.10.0")                 # numeric, not text comparison
        self.assertTrue(path.endswith(_setup("1.10.0")))

    def test_nothing_newer(self):
        self._touch(_setup("1.1.0"))
        self._touch(_setup("1.0.0"))
        self.assertIsNone(updater.find_update(self.tmp, "1.1.0"))

    def test_missing_folder(self):
        self.assertIsNone(updater.find_update(os.path.join(self.tmp, "nope"), "1.0.0"))
        self.assertIsNone(updater.find_update("", "1.0.0"))

    def test_github_release(self):
        import io
        import json
        from unittest import mock

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def latest(release):
            return mock.patch("urllib.request.urlopen", return_value=Resp(json.dumps(release).encode()))

        fixed = {"tag_name": "v9.1.0", "body": "New stuff", "assets": [
            {"name": "notes.txt", "browser_download_url": "https://x/notes.txt"},
            {"name": updater.SETUP_NAME, "browser_download_url": "https://x/" + updater.SETUP_NAME,
             "size": 123}]}
        with latest(fixed):
            self.assertEqual(updater.check_github("1.4.0"),
                             ("9.1.0", "https://x/" + updater.SETUP_NAME, 123, "New stuff"))
        with latest(fixed):
            self.assertIsNone(updater.check_github("9.1.0"))
        legacy = {"tag_name": "v9.2.0", "assets": [
            {"name": _setup("9.2.0"), "browser_download_url": "https://x/" + _setup("9.2.0")}]}
        with latest(legacy):
            self.assertEqual(updater.check_github("1.4.0")[:2], ("9.2.0", "https://x/" + _setup("9.2.0")))
        with latest({"tag_name": "v9.3.0", "assets": []}):
            self.assertIsNone(updater.check_github("1.4.0"))        # a release without the installer

if __name__ == "__main__":
    unittest.main()
