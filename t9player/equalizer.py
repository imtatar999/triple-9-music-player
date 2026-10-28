"""Graphic equalizer: 10 bands + preamp, the way a hi-fi amplifier's EQ works.

The band gains are turned into one linear-phase FIR filter (frequency sampling + Hann window) and
applied to the samples on their way out, block by block, with overlap-add. That keeps the whole thing
vectorised - one FFT pair per block, about 0.2 ms of a 46 ms block - so it runs in the audio callback
and the sound follows the sliders right away, with no re-decoding and no gap.

A flat setting produces a single unit impulse, so the audio comes out exactly as it went in (and the
engine then keeps the bit-perfect path instead of running the filter at all).

Boosting can push peaks past full scale, so the output passes a gentle limiter (the same idea as the
crossfade one): it drops at once when needed and comes back slowly, which is inaudible but keeps
loud, boosted music from clipping into crackles.
"""

import numpy as np

BANDS = (31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000)
MAX_DB = 12.0               # slider range of every band and of the preamp
TAPS = 4095                 # odd: exactly symmetric; long enough to shape the bass bands too
_DESIGN = 16384             # resolution the response curve is designed at
_CEILING = 0.989            # highest peak the limiter lets through (-0.1 dBFS)

PRESETS = {
    "Flat":          (0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
    "Bass boost":    (6, 5, 4, 2, 0, 0, 0, 0, 0, 0),
    "Bass cut":      (-6, -5, -4, -2, 0, 0, 0, 0, 0, 0),
    "Treble boost":  (0, 0, 0, 0, 0, 1, 2, 4, 5, 6),
    "Treble cut":    (0, 0, 0, 0, 0, -1, -2, -4, -5, -6),
    "Loudness":      (6, 5, 3, 0, -1, -1, 0, 2, 4, 5),
    "Vocal":         (-2, -2, -1, 2, 4, 4, 3, 1, 0, -1),
    "Rock":          (5, 4, 2, -1, -2, 0, 2, 4, 5, 5),
    "Pop":           (-1, 0, 2, 4, 4, 2, 0, -1, -1, -1),
    "Hip-hop":       (6, 5, 3, 1, -1, 0, 1, 2, 3, 3),
    "Electronic":    (5, 4, 1, 0, -2, 1, 1, 3, 4, 5),
    "Jazz":          (3, 2, 1, 2, -1, -1, 0, 1, 2, 3),
    "Classical":     (4, 3, 2, 0, -1, -1, 0, 2, 3, 4),
    "Podcast":       (-4, -3, -1, 3, 5, 5, 3, 1, -1, -3),
    "Headphones":    (4, 3, 1, 0, -1, -1, 1, 2, 3, 2),
    "Small speakers": (-5, -3, 2, 4, 3, 1, 1, 2, 3, 2),
}
FLAT = PRESETS["Flat"]


def clamp(gains):
    """A list of band gains, trimmed to the sliders' range and the right length."""
    out = [0.0] * len(BANDS)
    for i, value in enumerate(list(gains or [])[:len(BANDS)]):
        try:
            out[i] = max(-MAX_DB, min(MAX_DB, float(value)))
        except (TypeError, ValueError):
            out[i] = 0.0
    return out


def response(gains_db, preamp_db, freqs):
    """The curve the EQ applies, in dB, at the given frequencies (the dialog draws the same one).

    Between two sliders the curve eases from one to the other and flattens out at each slider, so
    there are no corners; below the first and above the last band it holds that band's value.
    """
    points_f = np.log10(np.asarray(BANDS, dtype=np.float64))
    points_g = np.asarray(clamp(gains_db), dtype=np.float64)
    lf = np.log10(np.maximum(np.asarray(freqs, dtype=np.float64), 1.0))
    i = np.clip(np.searchsorted(points_f, lf) - 1, 0, len(points_f) - 2)
    f0, f1 = points_f[i], points_f[i + 1]
    t = np.clip((lf - f0) / (f1 - f0), 0.0, 1.0)
    curve = points_g[i] + (points_g[i + 1] - points_g[i]) * (t * t * (3.0 - 2.0 * t))
    curve = np.where(lf <= points_f[0], points_g[0], curve)
    curve = np.where(lf >= points_f[-1], points_g[-1], curve)
    return curve + float(preamp_db)


def kernel(gains_db, preamp_db, rate, taps=TAPS):
    """Linear-phase FIR impulse response for one set of slider positions."""
    taps = min(int(taps) | 1, _DESIGN - 1)
    freqs = np.fft.rfftfreq(_DESIGN, 1.0 / float(rate))
    mag = 10.0 ** (response(gains_db, preamp_db, freqs) / 20.0)
    imp = np.roll(np.fft.irfft(mag, _DESIGN), _DESIGN // 2)
    half = taps // 2
    centre = _DESIGN // 2
    return (imp[centre - half:centre + half + 1] * np.hanning(taps)).astype(np.float32)


def is_flat(gains_db, preamp_db):
    return abs(float(preamp_db)) < 0.05 and all(abs(g) < 0.05 for g in clamp(gains_db))


def delay_seconds(rate):
    """How much later the sound leaves the filter (so the position stays honest)."""
    return (TAPS // 2) / float(rate) if rate else 0.0


class Equalizer:
    """Holds the current settings and filters the blocks that go to the sound card.

    `set()` is called from the engine thread, `process()` from the audio callback. They only share
    a counter and a tuple of plain numbers, so neither of them ever waits for the other.
    """

    def __init__(self):
        self.enabled = False
        self._params = (0.0, tuple(FLAT))
        self._version = 0
        self._kernel_key = None     # (version, rate) the impulse response was built for
        self._kernel = None
        self._spectrum_key = None   # (version, rate, nfft) the padded FFT was built for
        self._spectrum = None
        self._tail = None           # overlap-add remainder of the previous block
        self._limit = 1.0           # how much the limiter is holding the sound back right now

    # ------------------------------------------------------------------ engine thread
    def set(self, enabled, preamp_db, gains_db):
        self._params = (float(preamp_db), tuple(clamp(gains_db)))
        self.enabled = bool(enabled) and not is_flat(self._params[1], self._params[0])
        self._version += 1

    def reset(self):
        """Forget the overlap-add tail (after a seek, a stop or a new song)."""
        self._tail = None
        self._limit = 1.0

    # ------------------------------------------------------------------ audio callback
    def process(self, block, rate):
        """block: float32 [frames, 2]; returns the filtered block (or the same one when off)."""
        if not self.enabled or block.dtype != np.float32 or not len(block) or rate <= 0:
            return block
        frames = len(block)
        rate = int(rate)
        nfft = 1 << max(8, int(frames + TAPS - 1).bit_length())
        if self._kernel_key != (self._version, rate):
            preamp, gains = self._params
            self._kernel = kernel(gains, preamp, rate)
            self._kernel_key = (self._version, rate)
            self._spectrum_key = None
        if self._spectrum_key != (self._version, rate, nfft):
            # only the zero padding changes with the block size; the tail stays valid
            self._spectrum = np.fft.rfft(self._kernel, nfft)[:, None]
            self._spectrum_key = (self._version, rate, nfft)
        out = np.fft.irfft(np.fft.rfft(block, n=nfft, axis=0) * self._spectrum, n=nfft, axis=0)[:frames + TAPS - 1]
        if self._tail is not None and len(self._tail) == TAPS - 1:
            out[:TAPS - 1] += self._tail
        self._tail = out[frames:].copy()
        out = out[:frames]
        peak = float(np.abs(out).max())
        if peak > 0.0:
            need = min(1.0, _CEILING / peak)
            if need < self._limit:                       # too loud: duck right away
                out *= need
                self._limit = need
            elif self._limit < 1.0:                      # and come back gently
                end = min(need, self._limit + 0.02)
                out *= np.linspace(self._limit, end, frames)[:, None]
                self._limit = end
        return out.astype(np.float32, copy=False)
