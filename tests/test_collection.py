import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from t9player.collection import Collection, split_artists  # noqa: E402
from t9player.library import Track  # noqa: E402


def t(title, artist="Juice WRLD", album="", albumartist="", year="", track=0, plays=0):
    return Track(path=f"C:/m/{title}.mp3", title=title, artist=artist, album=album, albumartist=albumartist,
                 year=year, track=track, plays=plays)


class CollectionTests(unittest.TestCase):
    def test_split_artists(self):
        self.assertEqual(split_artists("Juice WRLD", "2 Seat (feat. G Herbo)"), ["Juice WRLD", "G Herbo"])
        self.assertEqual(split_artists("Juice WRLD, Lil Yachty"), ["Juice WRLD", "Lil Yachty"])
        self.assertEqual(split_artists("Future & Juice WRLD"), ["Future", "Juice WRLD"])
        self.assertEqual(split_artists("Juice WRLD feat. Halsey", "Life's A Mess (feat. Halsey)"), ["Juice WRLD", "Halsey"])

    def test_album_with_guests_in_album_artist_is_one_album(self):
        c = Collection([
            t("Lucid Dreams", album="Goodbye & Good Riddance", albumartist="Juice WRLD", year="2018", track=3),
            t("Wasted", album="Goodbye & Good Riddance", albumartist="Juice WRLD, Lil Uzi Vert", track=4),
            t("Intro", album="Goodbye & Good Riddance", track=1),
        ])
        self.assertEqual(len(c.albums), 1)
        album = next(iter(c.albums.values()))
        self.assertEqual(album.artist, "Juice WRLD")
        self.assertEqual([x.title for x in album.tracks], ["Intro", "Lucid Dreams", "Wasted"])
        self.assertEqual(album.year, "2018")

    def test_artists_and_their_albums(self):
        c = Collection([
            t("A", album="X", plays=3), t("B", album="Y"), t("C (feat. G Herbo)", album="X"),
            t("D", artist="Future"),
        ])
        juice = c.artist_named("juice wrld")
        self.assertEqual(len(juice.tracks), 3)
        self.assertEqual(sorted(a.title for a in juice.albums), ["X", "Y"])
        self.assertEqual(len(c.artist_named("G Herbo").tracks), 1)
        self.assertEqual(juice.cover_track.title, "A")          # most played song gives the picture
        self.assertIsNotNone(c.album_of(juice.tracks[0]))


if __name__ == "__main__":
    unittest.main()
