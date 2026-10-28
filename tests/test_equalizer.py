import unittest

import numpy as np

from t9player import equalizer as eq


def tone(hz, seconds=1.0, rate=44100, amp=0.25):
    t = np.arange(int(rate * seconds)) / rate
    wave = (np.sin(2 * np.pi * hz * t) * amp).astype(np.float32)
    return np.ascontiguousarray(np.vstack([wave, wave]).T)


def run(engine, block, rate=44100, size=2048):
    """Push a signal through the equalizer the way the audio callback does, block by block."""
    out = [engine.process(np.ascontiguousarray(block[i:i + size]), rate) for i in range(0, len(block), size)]
    return np.concatenate(out)


def level(samples, skip=22050):
    """Peak of the steady part (the first samples are the filter filling up)."""
    return float(np.abs(samples[skip:]).max())


def gain_db(samples, amp=0.25):
    return 20.0 * np.log10(max(level(samples), 1e-9) / amp)


class CurveTests(unittest.TestCase):
    def test_flat_is_a_single_impulse(self):
        k = eq.kernel(eq.FLAT, 0.0, 44100)
        self.assertAlmostEqual(k[len(k) // 2], 1.0, places=5)
        self.assertLess(float(np.abs(np.delete(k, len(k) // 2)).max()), 1e-6)

    def test_response_follows_the_sliders(self):
        gains = [0, 6, 0, 0, 0, 0, 0, 0, 0, -6]
        curve = eq.response(gains, 0.0, [62, 16000, 1000])
        self.assertAlmostEqual(curve[0], 6.0, places=6)
        self.assertAlmostEqual(curve[1], -6.0, places=6)
        self.assertAlmostEqual(curve[2], 0.0, places=6)
        # between two bands the curve slides from one to the other, it does not jump
        middle = eq.response([0, 6, 0, 0, 0, 0, 0, 0, 0, 0], 0.0, [88])[0]
        self.assertTrue(0.5 < middle < 6.0)

    def test_preamp_shifts_everything(self):
        self.assertAlmostEqual(eq.response(eq.FLAT, -3.0, [1000])[0], -3.0, places=6)

    def test_clamp_and_flat_detection(self):
        self.assertEqual(eq.clamp([99, -99, "x", None])[:4], [eq.MAX_DB, -eq.MAX_DB, 0.0, 0.0])
        self.assertEqual(len(eq.clamp([])), len(eq.BANDS))
        self.assertTrue(eq.is_flat(eq.FLAT, 0.0))
        self.assertFalse(eq.is_flat([0, 0, 0, 0, 0, 0, 0, 0, 0, 3], 0.0))
        self.assertFalse(eq.is_flat(eq.FLAT, 2.0))

    def test_every_preset_is_usable(self):
        for name, gains in eq.PRESETS.items():
            with self.subTest(preset=name):
                self.assertEqual(len(gains), len(eq.BANDS))
                self.assertEqual(eq.clamp(gains), [float(g) for g in gains])


class ProcessTests(unittest.TestCase):
    def setUp(self):
        self.eq = eq.Equalizer()

    def test_off_returns_the_same_samples(self):
        block = tone(1000, 0.2)
        self.eq.set(False, 0.0, [6] * 10)
        self.assertIs(self.eq.process(block, 44100), block)

    def test_flat_settings_switch_themselves_off(self):
        self.eq.set(True, 0.0, eq.FLAT)
        self.assertFalse(self.eq.enabled)          # nothing to do: stays bit-perfect

    def test_boosted_band_gets_louder_and_the_others_do_not(self):
        self.eq.set(True, 0.0, [0, 12, 0, 0, 0, 0, 0, 0, 0, 0])      # +12 dB at 62 Hz
        boosted = gain_db(run(self.eq, tone(62, 2.0)))
        self.eq.reset()
        untouched = gain_db(run(self.eq, tone(4000, 2.0)))
        self.assertAlmostEqual(boosted, 12.0, delta=1.5)        # bass bands are the hardest to shape
        self.assertAlmostEqual(untouched, 0.0, delta=0.3)

    def test_cut_band_gets_quieter(self):
        self.eq.set(True, 0.0, [0, 0, 0, 0, 0, 0, 0, -12, 0, 0])     # -12 dB at 4 kHz
        self.assertAlmostEqual(gain_db(run(self.eq, tone(4000, 2.0))), -12.0, delta=0.3)

    def test_preamp_changes_the_whole_signal(self):
        self.eq.set(True, -6.0, [0, 0, 0, 0, 0, 1, 0, 0, 0, 0])      # -6 preamp, +1 at 1 kHz
        self.assertAlmostEqual(gain_db(run(self.eq, tone(1000, 2.0))), -5.0, delta=0.3)

    def test_blocks_join_without_a_seam(self):
        """Overlap-add must give the same result as filtering the whole signal at once."""
        self.eq.set(True, 0.0, [6, 0, 0, 0, -4, 0, 0, 0, 0, 5])
        signal = tone(440, 1.0)
        small = run(self.eq, signal, size=1024)      # ends on a partial block, like PortAudio does
        self.eq.reset()
        big = run(self.eq, signal, size=8192)
        self.assertLess(float(np.abs(small - big).max()), 1e-5)

    def test_loud_boosted_music_does_not_clip(self):
        self.eq.set(True, 6.0, [12] * 10)
        out = run(self.eq, tone(200, 2.0, amp=0.9))
        self.assertLessEqual(float(np.abs(out).max()), 1.0)
        self.assertGreater(level(out), 0.5)                 # still loud, just held back

    def test_changing_the_sliders_takes_effect_immediately(self):
        self.eq.set(True, 0.0, [0, 0, 0, 0, 0, -12, 0, 0, 0, 0])
        quiet = gain_db(run(self.eq, tone(1000, 2.0)))
        self.eq.set(True, 0.0, [0, 0, 0, 0, 0, 12, 0, 0, 0, 0])   # no reset(): the filter changes mid-stream
        loud = gain_db(run(self.eq, tone(1000, 2.0)))
        self.assertAlmostEqual(loud - quiet, 24.0, delta=0.6)

    def test_other_sample_rates_work(self):
        for rate in (48000, 96000):
            with self.subTest(rate=rate):
                e = eq.Equalizer()
                e.set(True, 0.0, [0, 0, 0, 0, 0, 0, 0, 12, 0, 0])
                out = run(e, tone(4000, 2.0, rate=rate), rate=rate)
                self.assertAlmostEqual(gain_db(out), 12.0, delta=0.5)

    def test_group_delay_is_reported(self):
        self.assertAlmostEqual(eq.delay_seconds(44100), (eq.TAPS // 2) / 44100.0)
        self.assertAlmostEqual(eq.delay_seconds(0), 0.0)

    def test_odd_and_tiny_blocks(self):
        self.eq.set(True, 0.0, [3] * 10)
        for size in (64, 333, 4096):
            with self.subTest(size=size):
                self.eq.reset()
                out = run(self.eq, tone(1000, 0.5), size=size)
                self.assertEqual(out.dtype, np.float32)
                self.assertTrue(np.isfinite(out).all())


if __name__ == "__main__":
    unittest.main()
