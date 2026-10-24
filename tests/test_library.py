import os
import shutil
import tempfile
import threading
import unittest

from t9player import library as libmod


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.music = os.path.join(self.tmp, "Music")
        os.makedirs(self.music)
        for n in ("a.mp3", "b.mp3"):
            open(os.path.join(self.music, n), "wb").close()
        self.lib = libmod.Library(os.path.join(self.tmp, "lib.db"))
        self.lib.load()

    def tearDown(self):
        self.lib.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def scan(self):
        done = threading.Event()
        result = {}
        self.lib.scan([self.music], on_done=lambda r: (result.update(r), done.set()))
        self.assertTrue(done.wait(30))
        return result

    def test_unplugged_drive_keeps_the_library(self):
        self.scan()
        self.assertEqual(len(self.lib.library_tracks()), 2)
        away = self.music + "_away"
        os.rename(self.music, away)               # like pulling out the USB drive
        self.assertEqual(self.scan()["removed"], 0)
        self.assertEqual(len(self.lib.library_tracks()), 2)
        os.rename(away, self.music)

    def test_deleted_song_is_removed(self):
        self.scan()
        os.remove(os.path.join(self.music, "a.mp3"))
        self.assertEqual(self.scan()["removed"], 1)
        self.assertEqual([os.path.basename(t.path) for t in self.lib.library_tracks()], ["b.mp3"])


if __name__ == "__main__":
    unittest.main()
