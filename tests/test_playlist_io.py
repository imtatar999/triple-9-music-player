import os
import tempfile
import unittest

from t9player import playlist_io
from t9player.library import Track


def track(path, title, artist, album="", duration=200.0):
    return Track(path=path, title=title, artist=artist, album=album, duration=duration)


class PlaylistIOTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.music = os.path.join(root, "Music", "Juice WRLD")
        os.makedirs(os.path.join(self.music, "WOD"))
        self.lib = []
        for i, (title, album) in enumerate((("Lucid Dreams", "GBGR"), ("Robbery", "DRFL"), ("Wishing Well", "LND"))):
            p = os.path.join(self.music, f"{i + 1:02d} {title}.mp3")
            open(p, "wb").close()
            self.lib.append(track(p, title, "Juice WRLD", album, 200 + i * 10))
        # two files with the same name in different folders
        a = os.path.join(self.music, "Extra.mp3")
        b = os.path.join(self.music, "WOD", "Extra.mp3")
        for p in (a, b):
            open(p, "wb").close()
        self.lib.append(track(a, "Extra (For Fun)", "Juice WRLD", "WOD ERA", 201))
        self.lib.append(track(b, "Extra (For Fun) (Sessions)", "Juice WRLD", "WOD (Sessions)", 268))

    def tearDown(self):
        self.tmp.cleanup()

    def roundtrip(self, ext, relative=True):
        target = os.path.join(self.tmp.name, "out" + ext)
        playlist_io.write(target, "Mix 999", self.lib, relative=relative)
        name, entries = playlist_io.read(target)
        found, missing = playlist_io.resolve(entries, self.lib, target)
        return name, found, missing

    def test_every_format_roundtrips(self):
        for ext in (".m3u8", ".m3u", ".pls", ".xspf", ".wpl", ".json"):
            with self.subTest(ext=ext):
                name, found, missing = self.roundtrip(ext)
                self.assertEqual(found, [t.path for t in self.lib])
                self.assertEqual(missing, [])
                if ext in (".m3u8", ".m3u", ".xspf", ".json"):
                    self.assertEqual(name, "Mix 999")

    def test_other_computer_other_folder(self):
        # made on a PC where the music lived in D:\Rap\Juice WRLD\...
        text = "#EXTM3U\n" + "\n".join(
            f"#EXTINF:{int(t.duration)},{t.artist} - {t.title}\n"
            + t.path.replace(os.path.dirname(self.music), r"D:\Rap") for t in self.lib)
        p = os.path.join(self.tmp.name, "other.m3u")
        open(p, "w", encoding="utf-8").write(text)
        _, entries = playlist_io.read(p)
        found, missing = playlist_io.resolve(entries, self.lib, p)
        self.assertEqual(found, [t.path for t in self.lib])
        self.assertFalse(missing)

    def test_tags_only_and_ampwave_style(self):
        # Ampwave writes "Artist - Title" where the path would be
        text = ("#EXTM3U\n#PLAYLIST:From iPhone\n#EXTINF:210,Juice WRLD - Robbery\n#AMPWAVE-ALBUM:DRFL\n"
                "Juice WRLD - Robbery\n#EXTINF:268,Juice WRLD - Extra (For Fun) (Sessions)\n"
                "Juice WRLD - Extra (For Fun) (Sessions)\n#EXTINF:100,Somebody - Not Here\nSomebody - Not Here\n")
        p = os.path.join(self.tmp.name, "a.m3u")
        open(p, "w", encoding="utf-8").write(text)
        name, entries = playlist_io.read(p)
        found, missing = playlist_io.resolve(entries, self.lib, p)
        self.assertEqual(name, "From iPhone")
        self.assertEqual(found, [self.lib[1].path, self.lib[4].path])
        self.assertEqual([m.label() for m in missing], ["Somebody - Not Here"])

    def test_same_file_name_uses_tags(self):
        p = os.path.join(self.tmp.name, "b.m3u8")
        open(p, "w", encoding="utf-8").write("#EXTINF:268,Juice WRLD - Extra (For Fun) (Sessions)\nX:\\old\\Extra.mp3\n")
        _, entries = playlist_io.read(p)
        found, _ = playlist_io.resolve(entries, self.lib, p)
        self.assertEqual(found, [self.lib[4].path])

    def test_ampwave_json(self):
        p = os.path.join(self.tmp.name, "c.json")
        open(p, "w", encoding="utf-8").write(
            '{"format":"ampwave-playlist","version":2,"name":"Phone","exportedAt":"2026-01-01T00:00:00Z",'
            '"tracks":[{"songName":"Wishing Well","artistName":"Juice WRLD","duration":220}]}')
        name, entries = playlist_io.read(p)
        found, _ = playlist_io.resolve(entries, self.lib, p)
        self.assertEqual((name, found), ("Phone", [self.lib[2].path]))

    def resolve_file(self, name, data):
        p = os.path.join(self.tmp.name, name)
        open(p, "wb").write(data if isinstance(data, bytes) else data.encode("utf-8"))
        title, entries = playlist_io.read(p)
        return title, playlist_io.resolve(entries, self.lib, p)[0]

    def test_foobar_fpl(self):
        # binary header, then zero-terminated 'file://' paths in order, with other data in between
        blob = b"\xe1\xa0\x9c\x91\xf8\x3c\x77\x42\x85\x2c\x3b\xcc\x14\x01\xd3\xf2" + b"\x00\x10\x00\x00"
        for t in (self.lib[2], self.lib[0]):
            blob += b"file://" + t.path.encode("utf-8") + b"\x00" + b"Juice WRLD\x00" + b"\x01\x02\x00\x00"
        name, found = self.resolve_file("Default.fpl", blob)
        self.assertEqual((name, found), ("Default", [self.lib[2].path, self.lib[0].path]))

    def test_foobar_fplite_and_txt(self):
        text = "".join("file://" + t.path + "\n" for t in self.lib[:2])
        self.assertEqual(self.resolve_file("x.fplite", text)[1], [t.path for t in self.lib[:2]])
        self.assertEqual(self.resolve_file("x.txt", "\n".join(t.path for t in self.lib[1:3]))[1],
                         [t.path for t in self.lib[1:3]])

    def test_wpl_and_asx_from_other_players(self):
        rel = os.path.relpath(self.lib[1].path, self.tmp.name)
        wpl = ('<?wpl version="1.0"?><smil><head><title>WMP & Co</title></head><body><seq>'
               f'<media src="{rel}" tid="{{1}}"/></seq></body></smil>')
        self.assertEqual(self.resolve_file("w.wpl", wpl), ("WMP & Co", [self.lib[1].path]))
        asx = ('<ASX version="3.0"><TITLE>Old</TITLE><ENTRY><TITLE>Wishing Well</TITLE><AUTHOR>Juice WRLD</AUTHOR>'
               '<REF HREF="Z:\\gone\\Wishing Well.wma"/></ENTRY></ASX>')
        self.assertEqual(self.resolve_file("a.asx", asx), ("Old", [self.lib[2].path]))

    def test_tricky_file_names(self):
        # '#1 Hit' looked like an m3u comment, a leading space got trimmed away
        extra = []
        for n in ("#1 Hit.mp3", "  spacje  .mp3", "Żółć & Łzy – 日本語 🎵.mp3", "100% #2;a=b.mp3"):
            p = os.path.join(self.music, n)
            open(p, "wb").close()
            extra.append(track(p, n, "Someone"))
        self.lib += extra
        for ext in (".m3u8", ".pls", ".xspf", ".wpl", ".json"):
            with self.subTest(ext=ext):
                _, found, missing = self.roundtrip(ext)
                self.assertEqual(found, [t.path for t in self.lib])

    def test_broken_file(self):
        p = os.path.join(self.tmp.name, "d.json")
        open(p, "w", encoding="utf-8").write("{not json")
        with self.assertRaises(ValueError):
            playlist_io.read(p)


if __name__ == "__main__":
    unittest.main()
