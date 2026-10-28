import os
import shutil
import tempfile
import unittest

from t9player import library as libmod, relocate
from t9player.library import Track


def make(path, size=1000, **kw):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(b"x" * size)
    return Track(path=path, size=size, **kw)


class MatchTests(unittest.TestCase):
    def test_same_structure_other_root(self):
        old = [Track(path=r"D:\Music\Juice WRLD\GBGR\01 Intro.mp3", size=10),
               Track(path=r"D:\Music\Juice WRLD\WOD\01 Intro.mp3", size=10)]
        files = {r"E:\Muzyka\Juice WRLD\GBGR\01 Intro.mp3": 10, r"E:\Muzyka\Juice WRLD\WOD\01 Intro.mp3": 10}
        moves = relocate.find_moves(old, files)
        self.assertEqual(moves[old[0].path], r"E:\Muzyka\Juice WRLD\GBGR\01 Intro.mp3")
        self.assertEqual(moves[old[1].path], r"E:\Muzyka\Juice WRLD\WOD\01 Intro.mp3")

    def test_works_across_windows_and_mac_paths(self):
        old = [Track(path="D:\\Music\\Album\\Song.mp3", size=5)]
        moves = relocate.find_moves(old, {"/Users/me/Music/Album/Song.mp3": 5})
        self.assertEqual(moves, {old[0].path: "/Users/me/Music/Album/Song.mp3"})

    def test_flat_folder_unique_names(self):
        old = [Track(path=r"D:\a\b\Song One.mp3", size=1), Track(path=r"D:\a\c\Song Two.mp3", size=2)]
        files = {r"E:\all\Song One.mp3": 1, r"E:\all\Song Two.mp3": 2}
        self.assertEqual(len(relocate.find_moves(old, files)), 2)

    def test_same_name_different_albums_are_not_guessed(self):
        old = [Track(path=r"D:\x\A\Intro.mp3", size=5), Track(path=r"D:\x\B\Intro.mp3", size=5)]
        files = {r"E:\all\Intro.mp3": 5, r"E:\all2\Intro.mp3": 5}
        self.assertEqual(relocate.find_moves(old, files), {})

    def test_other_recording_with_same_name_is_rejected(self):
        old = [Track(path=r"D:\x\Song.mp3", size=1, duration=200.0)]
        tags = {r"E:\y\Song.mp3": ("Song", "A", "", 320.0)}
        self.assertEqual(relocate.find_moves(old, {r"E:\y\Song.mp3": 9}, lambda p: tags[p]), {})

    def test_renamed_file_found_by_tags(self):
        old = [Track(path=r"D:\x\old name.mp3", title="Lucid Dreams", artist="Juice WRLD", album="GBGR", duration=239.0)]
        tags = {r"E:\y\01 Lucid Dreams.mp3": ("Lucid Dreams", "Juice WRLD", "GBGR", 239.4),
                r"E:\y\02 Other.mp3": ("Other", "Juice WRLD", "GBGR", 150.0)}
        files = {p: 1 for p in tags}
        moves = relocate.find_moves(old, files, lambda p: tags[p])
        self.assertEqual(moves, {old[0].path: r"E:\y\01 Lucid Dreams.mp3"})

    def test_a_file_is_used_once(self):
        old = [Track(path=r"D:\1\Song.mp3", size=5, title="S", artist="A"),
               Track(path=r"D:\2\Song.mp3", size=5, title="S", artist="A")]
        moves = relocate.find_moves(old, {r"E:\1\Song.mp3": 5}, lambda p: ("S", "A", "", 0.0))
        self.assertEqual(list(moves.values()), [r"E:\1\Song.mp3"])


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.lib = libmod.Library(os.path.join(self.tmp, "lib.db"))
        self.lib.load()
        self.old_dir = os.path.join(self.tmp, "OldDrive", "Music")
        self.new_dir = os.path.join(self.tmp, "NewDrive", "Muzyka")

    def tearDown(self):
        self.lib.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def add(self, rel, **kw):
        t = make(os.path.join(self.old_dir, rel), title=os.path.basename(rel), artist="A", in_library=1, **kw)
        self.lib._upsert([t])
        self.lib.tracks[t.path] = t
        self.lib._update(t.path, plays=kw.get("plays", 0), favorite=kw.get("favorite", 0))
        return t

    def move_music(self):
        os.makedirs(os.path.dirname(self.new_dir), exist_ok=True)
        shutil.move(self.old_dir, self.new_dir)

    def test_missing_detects_only_what_matters(self):
        a = self.add("Album/a.mp3", plays=3)
        self.assertEqual(self.lib.missing_tracks(), [])
        self.move_music()
        self.assertEqual([t.path for t in self.lib.missing_tracks()], [a.path])

    def test_moved_music_keeps_plays_favorites_and_playlists(self):
        a = self.add("Album/a.mp3", plays=7, favorite=1)
        b = self.add("Album/b.mp3", plays=2)
        pid = self.lib.create_playlist("Mix")
        self.lib.set_playlist_paths(pid, [b.path, a.path])
        old_a = a.path
        self.move_music()
        result = self.lib.relocate_from([self.new_dir])
        self.assertEqual((result["missing"], result["found"], result["left"]), (2, 2, 0))
        new_a = os.path.join(self.new_dir, "Album", "a.mp3")
        new_b = os.path.join(self.new_dir, "Album", "b.mp3")
        self.assertEqual((self.lib.get(new_a).plays, self.lib.get(new_a).favorite), (7, 1))
        self.assertEqual(self.lib.get(new_b).plays, 2)
        self.assertIsNone(self.lib.get(old_a))
        self.assertEqual(self.lib.playlist_paths(pid), [new_b, new_a])
        # and it is all in the database, not only in memory
        reopened = libmod.Library(self.lib.db_path)
        reopened.load()
        self.assertEqual(reopened.get(new_a).plays, 7)
        self.assertEqual(reopened.playlist_paths(pid), [new_b, new_a])
        reopened.close()
        self.assertEqual(self.lib.missing_tracks(), [])

    def test_old_entry_hidden_and_new_entry_scanned_earlier_get_merged(self):
        """What happened to the user: old folder removed (songs hidden), new folder added (songs as new entries, 0 plays)."""
        a = self.add("Album/a.mp3", plays=12, favorite=1)
        self.move_music()
        self.lib.remove_folder_tracks(self.old_dir, [])           # the old folder was removed in the settings
        fresh = Track(path=os.path.join(self.new_dir, "Album", "a.mp3"), title="a.mp3", artist="A", in_library=1, size=1000)
        self.lib._upsert([fresh])
        self.lib.tracks[fresh.path] = fresh
        self.assertEqual(fresh.plays, 0)
        self.assertEqual([t.path for t in self.lib.missing_tracks()], [a.path])    # it has history, so it is found
        result = self.lib.relocate_from([self.new_dir])
        self.assertEqual(result["found"], 1)
        merged = self.lib.get(fresh.path)
        self.assertEqual((merged.plays, merged.favorite, merged.in_library), (12, 1, 1))
        self.assertIsNone(self.lib.get(a.path))
        self.assertEqual(len(self.lib.tracks), 1)

    def test_songs_not_in_the_new_folder_stay_missing(self):
        a = self.add("Album/a.mp3", plays=1)
        self.add("Album/gone.mp3", plays=1)
        self.move_music()
        os.remove(os.path.join(self.new_dir, "Album", "gone.mp3"))
        result = self.lib.relocate_from([self.new_dir])
        self.assertEqual((result["found"], result["left"]), (1, 1))


if __name__ == "__main__":
    unittest.main()
