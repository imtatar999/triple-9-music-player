import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from t9player import updater  # noqa: E402


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="t9upd_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _touch(self, name):
        open(os.path.join(self.tmp, name), "wb").close()

    def test_picks_newest_newer_version(self):
        for name in ("T9MusicPlayer-Setup-1.0.9.exe", "T9MusicPlayer-Setup-1.2.0.exe",
                     "T9MusicPlayer-Setup-1.10.0.exe", "notes.txt", "T9MusicPlayer-Setup-x.exe"):
            self._touch(name)
        version, path = updater.find_update(self.tmp, "1.1.0")
        self.assertEqual(version, "1.10.0")                 # numeric, not text comparison
        self.assertTrue(path.endswith("T9MusicPlayer-Setup-1.10.0.exe"))

    def test_nothing_newer(self):
        self._touch("T9MusicPlayer-Setup-1.1.0.exe")
        self._touch("T9MusicPlayer-Setup-1.0.0.exe")
        self.assertIsNone(updater.find_update(self.tmp, "1.1.0"))

    def test_missing_folder(self):
        self.assertIsNone(updater.find_update(os.path.join(self.tmp, "nope"), "1.0.0"))
        self.assertIsNone(updater.find_update("", "1.0.0"))

    def test_github_release(self):
        import io
        import json
        from unittest import mock

        release = {"tag_name": "v9.1.0", "assets": [
            {"name": "notes.txt", "browser_download_url": "https://x/notes.txt"},
            {"name": "T9MusicPlayer-Setup-9.1.0.exe", "browser_download_url": "https://x/T9MusicPlayer-Setup-9.1.0.exe",
             "size": 123}]}

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with mock.patch("urllib.request.urlopen", return_value=Resp(json.dumps(release).encode())):
            self.assertEqual(updater.check_github("1.4.0"), ("9.1.0", "https://x/T9MusicPlayer-Setup-9.1.0.exe", 123))
        with mock.patch("urllib.request.urlopen", return_value=Resp(json.dumps(release).encode())):
            self.assertIsNone(updater.check_github("9.1.0"))


if __name__ == "__main__":
    unittest.main()
