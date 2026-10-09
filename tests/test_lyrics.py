import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from t9player import lyrics, meta  # noqa: E402


class LrcTests(unittest.TestCase):
    def test_basic(self):
        lyr = lyrics.parse_lrc("[ti:x]\n[00:04.26] Oh-woah\n[00:06.39] Ooh-oh\n\n[01:02.5]Third")
        self.assertTrue(lyr.synced)
        self.assertEqual([round(ln.time, 2) for ln in lyr.lines], [4.26, 6.39, 62.5])
        self.assertEqual(lyr.lines[0].text, "Oh-woah")
        self.assertEqual(lyr.index_at(0), -1)
        self.assertEqual(lyr.index_at(5.0), 0)
        self.assertEqual(lyr.index_at(100), 2)

    def test_multi_stamps_and_offset(self):
        lyr = lyrics.parse_lrc("[offset:+500]\n[00:10.00][00:20.00]Chorus\n[00:15.00]Verse")
        self.assertEqual([ln.text for ln in lyr.lines], ["Chorus", "Verse", "Chorus"])
        self.assertAlmostEqual(lyr.lines[0].time, 9.5)

    def test_formats(self):
        lyr = lyrics.parse_lrc("[1:02]a\n[01:03.123]b\n[01:04:50]c\n[1:00:00.00]d")
        self.assertEqual([round(ln.time, 3) for ln in lyr.lines], [62.0, 63.123, 64.5, 3600.0])

    def test_word_timing(self):
        lyr = lyrics.parse_lrc("[00:12.00]<00:12.00>Hey <00:12.40>hey <00:13.00>you\n[00:15.00]next")
        line = lyr.lines[0]
        self.assertEqual(line.text, "Hey hey you")
        self.assertEqual(len(line.words), 3)
        self.assertEqual("".join(w.text for w in line.words), line.text)
        self.assertAlmostEqual(line.words[1].time, 12.4)
        self.assertTrue(lyr.has_words)

    def test_instrumental_gap(self):
        lyr = lyrics.parse_lrc("[00:01.00]a\n[00:05.00]\n[00:06.00]\n[00:20.00]b\n[00:30.00]")
        self.assertEqual([ln.text for ln in lyr.lines], ["a", lyrics.INSTRUMENTAL, "b"])

    def test_plain(self):
        lyr = lyrics.parse_any("Line one\nLine two\n\nLine three")
        self.assertFalse(lyr.synced)
        self.assertEqual(len(lyr.lines), 4)

    def test_decode(self):
        self.assertEqual(lyrics.decode_text_file("Zażółć".encode("utf-8")), "Zażółć")
        self.assertEqual(lyrics.decode_text_file("Zażółć".encode("cp1250")), "Zażółć")
        self.assertEqual(lyrics.decode_text_file("Hej".encode("utf-16")), "Hej")


class SidecarTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="t9lyr_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _touch(self, rel, text=""):
        path = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def test_lrc_next_to_song(self):
        song = self._touch("Song.mp3")
        self._touch("Song.lrc", "[00:01.00]a\n[00:02.00]b")
        lyr = meta.find_lyrics(song)
        self.assertTrue(lyr.synced)
        self.assertEqual(lyr.source, "Sidecar .lrc")

    def test_synced_lyrics_subfolder_and_odd_spacing(self):
        song = self._touch("5 Bitches (500 Carats) (Sessions) (WOD) .mp3")
        self._touch("SYNCED LYRICS/5 Bitches (500 Carats) (Sessions) (WOD).lrc", "[00:01.00]a\n[00:02.00]b")
        lyr = meta.find_lyrics(song)
        self.assertIsNotNone(lyr)
        self.assertTrue(lyr.synced)

    def test_txt_fallback(self):
        song = self._touch("Other.mp3")
        self._touch("LYRICS/Other.txt", "plain words\nmore")
        lyr = meta.find_lyrics(song)
        self.assertFalse(lyr.synced)
        self.assertEqual(lyr.lines[0].text, "plain words")

    def _mp3_with_embedded(self, name, text):
        import av
        import numpy as np
        from mutagen.id3 import ID3, USLT
        path = os.path.join(self.tmp, name)
        out = av.open(path, "w")
        stream = out.add_stream("libmp3lame", rate=44100, layout="stereo")
        frame = av.AudioFrame.from_ndarray(np.zeros((2, 44100), np.float32), format="fltp", layout="stereo")
        frame.sample_rate = 44100
        for packet in list(stream.encode(frame)) + list(stream.encode(None)):
            out.mux(packet)
        out.close()
        tags = ID3()
        tags.add(USLT(encoding=3, lang="eng", desc="", text=text))
        tags.save(path)
        return path

    def test_embedded_beats_lrc_by_default(self):
        song = self._mp3_with_embedded("Both.mp3", "[00:01.00]embedded one\n[00:02.00]embedded two")
        self._touch("SYNCED LYRICS/Both.lrc", "[00:01.00]file one\n[00:02.00]file two")
        self.assertEqual(meta.find_lyrics(song).lines[0].text, "embedded one")
        self.assertEqual(meta.find_lyrics(song, ["lrc", "embedded", "txt"]).lines[0].text, "file one")

    def test_synced_lrc_beats_plain_embedded(self):
        song = self._mp3_with_embedded("Plain.mp3", "just words\nno timing")
        self._touch("Plain.lrc", "[00:01.00]timed\n[00:02.00]line")
        lyr = meta.find_lyrics(song)
        self.assertTrue(lyr.synced)
        self.assertEqual(lyr.lines[0].text, "timed")

    def test_order_normalized(self):
        self.assertEqual(meta.normalize_lyrics_order(["txt", "bogus", "txt"]), ["txt", "embedded", "lrc"])

    def test_nothing(self):
        song = self._touch("Lonely.mp3")
        self.assertIsNone(meta.find_lyrics(song))


if __name__ == "__main__":
    unittest.main()
