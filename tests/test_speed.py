import os
import shutil
import tempfile
import unittest

import numpy as np

from t9player.audio import Decoder
from test_loudness import tone      # a generated FLAC tone


def dominant_hz(samples, rate):
    mono = samples[:, 0] if samples.ndim == 2 else samples
    spectrum = np.abs(np.fft.rfft(mono * np.hanning(len(mono))))
    return float(np.argmax(spectrum) * rate / len(mono))


class SpeedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.path = tone(os.path.join(cls.tmp, "t.flac"), 0.5, seconds=10.0, freq=1000)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def play(self, speed, start=0.0):
        d = Decoder(self.path, start=start)
        d.force_float()
        d.set_speed(speed)
        blocks, times = [], []
        while True:
            got = d.read()
            if got is None:
                break
            blocks.append(got[0])
            times.append(got[1])
        rate, chunk_rate = d.rate, d.chunk_rate
        d.close()
        return np.concatenate(blocks), times, rate, chunk_rate

    def test_normal_speed_is_untouched(self):
        data, _, rate, chunk_rate = self.play(1.0)
        self.assertEqual(chunk_rate, rate)
        self.assertAlmostEqual(len(data) / rate, 10.0, delta=0.05)

    def test_faster_is_shorter_and_keeps_the_pitch(self):
        for speed in (1.5, 2.0):
            with self.subTest(speed=speed):
                data, times, rate, chunk_rate = self.play(speed)
                self.assertAlmostEqual(len(data) / rate, 10.0 / speed, delta=0.15)       # nothing lost at the end
                self.assertAlmostEqual(chunk_rate, rate / speed)
                mid = data[rate:rate * 2]
                self.assertAlmostEqual(dominant_hz(mid, rate), 1000.0, delta=15.0)      # not chipmunk
                self.assertGreater(float(np.abs(mid).max()), 0.4)

    def test_song_time_of_each_block_follows_the_speed(self):
        data, times, rate, chunk_rate = self.play(2.0)
        # block start times are song seconds, increasing, ending near the end of the 10 s song
        self.assertTrue(all(b > a for a, b in zip(times, times[1:])))
        self.assertGreater(times[-1], 9.0)

    def test_seek_then_speed(self):
        data, _, rate, _ = self.play(1.5, start=4.0)
        self.assertAlmostEqual(len(data) / rate, 6.0 / 1.5, delta=0.2)


if __name__ == "__main__":
    unittest.main()
