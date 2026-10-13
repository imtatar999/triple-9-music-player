import os
import shutil
import tempfile
import unittest

import numpy as np

from t9player import loudness
from t9player.audio import Decoder


def tone(path, amplitude, seconds=6.0, rate=44100, freq=1000):
    import av
    with av.open(path, "w") as out:
        st = out.add_stream("flac", rate=rate)
        st.layout = "stereo"
        t = np.arange(int(rate * seconds)) / rate
        data = (np.sin(2 * np.pi * freq * t) * amplitude * 32767).astype(np.int16)
        frame = av.AudioFrame.from_ndarray(np.ascontiguousarray(np.vstack([data, data]).T.reshape(1, -1)),
                                           format="s16", layout="stereo")
        frame.rate = rate
        for p in st.encode(frame):
            out.mux(p)
        for p in st.encode(None):
            out.mux(p)
    return path


class LoudnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.loud = tone(os.path.join(cls.tmp, "loud.flac"), 0.9)
        cls.quiet = tone(os.path.join(cls.tmp, "quiet.flac"), 0.09)      # 20 dB quieter

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_measure_sees_the_difference(self):
        loud, peak_l = loudness.measure(self.loud)
        quiet, peak_q = loudness.measure(self.quiet)
        self.assertAlmostEqual(loud - quiet, 20.0, delta=0.3)
        self.assertAlmostEqual(peak_l, 0.9, delta=0.02)

    def test_gain_brings_loud_down_and_never_clips(self):
        loud, peak_l = loudness.measure(self.loud)
        quiet, peak_q = loudness.measure(self.quiet)
        g_loud = loudness.gain_for(loud, peak_l)
        g_quiet = loudness.gain_for(quiet, peak_q)
        self.assertLess(g_loud, 1.0)
        self.assertAlmostEqual(loud + 20 * np.log10(g_loud), loudness.TARGET_LUFS, delta=0.1)
        # the quiet one wants +20 dB but may only go as far as its peak allows (and +10 dB at most)
        self.assertLessEqual(peak_q * g_quiet, loudness.HEADROOM + 1e-6)
        self.assertLessEqual(20 * np.log10(g_quiet), loudness.MAX_BOOST_DB + 1e-6)

    def test_album_loudness_is_an_energy_average(self):
        self.assertAlmostEqual(loudness.album_lufs([-10.0, -10.0]), -10.0)
        self.assertAlmostEqual(loudness.album_lufs([-10.0, None]), -10.0)
        self.assertGreater(loudness.album_lufs([-10.0, -20.0]), -15.0)

    def test_decoder_applies_and_glides_to_the_gain(self):
        def level(gain, target=None):
            d = Decoder(self.loud)
            d.force_float()
            d.gain = gain
            d.gain_target = gain if target is None else target
            blocks = []
            while True:
                got = d.read()
                if got is None:
                    break
                blocks.append(got[0])
            d.close()
            return np.concatenate(blocks)
        plain = level(1.0)
        half = level(0.5)
        self.assertAlmostEqual(float(np.abs(half).max()), float(np.abs(plain).max()) * 0.5, delta=0.01)
        glide = level(1.0, 0.5)
        self.assertAlmostEqual(float(np.abs(glide[-44100:]).max()), float(np.abs(plain).max()) * 0.5, delta=0.01)
        self.assertGreater(float(np.abs(glide[:2000]).max()), 0.8)     # starts at the old level, no jump

    def test_replaygain_tags_are_used(self):
        import mutagen.flac
        p = os.path.join(self.tmp, "tagged.flac")
        shutil.copy(self.loud, p)
        f = mutagen.flac.FLAC(p)
        f["REPLAYGAIN_TRACK_GAIN"] = "-6.50 dB"
        f["REPLAYGAIN_TRACK_PEAK"] = "0.950000"
        f.save()
        lufs, peak = loudness.read_tags(p)
        self.assertAlmostEqual(lufs, loudness.RG_REFERENCE + 6.5)
        self.assertAlmostEqual(peak, 0.95)


if __name__ == "__main__":
    unittest.main()
