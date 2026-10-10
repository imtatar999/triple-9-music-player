"""Decoder tests: lossless formats must come out bit-identical, every format must play.

Run:  python -m unittest discover -s tests
"""

import os
import shutil
import sys
import tempfile
import unittest

import av
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from t9player import audio, meta  # noqa: E402


def _signal(rate, seconds, bits):
    """Stereo test signal using the full integer range of `bits` (noise + sine)."""
    rng = np.random.default_rng(1234)
    n = int(rate * seconds)
    t = np.arange(n) / rate
    peak = 2 ** (bits - 1) - 1
    sine = 0.6 * np.sin(2 * np.pi * 997 * t)
    left = np.round((sine + 0.3 * rng.uniform(-1, 1, n)) * peak)
    right = np.round((-sine + 0.3 * rng.uniform(-1, 1, n)) * peak)
    return np.clip(np.stack([left, right], axis=1), -peak - 1, peak).astype(np.int64)


def _encode(path, codec, rate, bits, samples, container_fmt=None):
    """Write integer samples with PyAV. 24-bit values go into the top of s32."""
    out = av.open(path, "w", format=container_fmt)
    stream = out.add_stream(codec, rate=rate, layout="stereo")
    if bits == 16:
        fmt, data = "s16", samples.astype(np.int16)
    else:
        fmt, data = "s32", (samples.astype(np.int64) << (32 - bits)).astype(np.int32)
    stream.format = fmt if codec != "alac" else fmt + "p"
    block = 4096
    for start in range(0, len(data), block):
        chunk = data[start:start + block]
        if codec == "alac":
            frame = av.AudioFrame.from_ndarray(np.ascontiguousarray(chunk.T), format=fmt + "p", layout="stereo")
        else:
            frame = av.AudioFrame.from_ndarray(chunk.reshape(1, -1), format=fmt, layout="stereo")
        frame.sample_rate = rate
        frame.pts = start
        for packet in stream.encode(frame):
            out.mux(packet)
    for packet in stream.encode(None):
        out.mux(packet)
    out.close()


def _decode_all(path, start=0.0):
    dec = audio.Decoder(path, start=start)
    blocks = []
    while True:
        got = dec.read()
        if got is None:
            break
        blocks.append(got[0])
    dec.close()
    return dec, np.concatenate(blocks)


class LosslessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="t9test_")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _roundtrip(self, name, codec, rate, bits, container=None):
        src = _signal(rate, 1.5, bits)
        path = os.path.join(self.tmp, name)
        _encode(path, codec, rate, bits, src, container)
        dec, out = _decode_all(path)
        self.assertEqual(dec.rate, rate, "sample rate must stay native")
        self.assertTrue(dec.native)
        if bits == 16:
            self.assertEqual(out.dtype, np.int16)
            got = out.astype(np.int64)
        else:
            self.assertEqual(out.dtype, np.int32)
            got = out.astype(np.int64) >> (32 - bits)
        self.assertEqual(got.shape, src.shape)
        self.assertTrue(np.array_equal(got, src), f"{name}: samples differ - not bit-perfect")
        return path

    def test_flac_24_96(self):
        self._roundtrip("hires.flac", "flac", 96000, 24)

    def test_flac_16_44(self):
        self._roundtrip("cd.flac", "flac", 44100, 16)

    def test_flac_24_192(self):
        self._roundtrip("ultra.flac", "flac", 192000, 24)

    def test_wav_16(self):
        self._roundtrip("cd.wav", "pcm_s16le", 44100, 16)

    def test_wav_24(self):
        self._roundtrip("studio.wav", "pcm_s24le", 48000, 24)

    def test_aiff_16(self):
        self._roundtrip("cd.aiff", "pcm_s16be", 44100, 16, "aiff")

    def test_alac_16(self):
        self._roundtrip("cd.m4a", "alac", 44100, 16, "ipod")

    def test_exact_seek(self):
        """After a seek the very first sample must be the right one."""
        rate = 44100
        src = _signal(rate, 3.0, 16)
        path = os.path.join(self.tmp, "seek.flac")
        _encode(path, "flac", rate, 16, src)
        dec, out = _decode_all(path, start=1.25)
        first = int(round(1.25 * rate))
        self.assertTrue(np.array_equal(out[:2000].astype(np.int64), src[first:first + 2000]))

    def test_lossy_formats_play(self):
        rate = 48000
        src = _signal(rate, 1.0, 16)
        for name, codec, fmt in (("a.mp3", "libmp3lame", None), ("a.ogg", "libvorbis", None),
                                 ("a.opus", "libopus", None), ("a.m4a", "aac", "ipod")):
            if codec not in av.codecs_available:
                continue
            path = os.path.join(self.tmp, name)
            try:
                out = av.open(path, "w", format=fmt)
                stream = out.add_stream(codec, rate=rate, layout="stereo")
                fmts = [f.name for f in stream.codec_context.codec.audio_formats or []]
                use = fmts[0] if fmts else "fltp"
                resampler = av.AudioResampler(format=use, layout="stereo", rate=rate)
                for start in range(0, len(src), 2048):
                    frame = av.AudioFrame.from_ndarray(src[start:start + 2048].astype(np.int16).reshape(1, -1),
                                                       format="s16", layout="stereo")
                    frame.sample_rate = rate
                    for rf in resampler.resample(frame):
                        for packet in stream.encode(rf):
                            out.mux(packet)
                for packet in stream.encode(None):
                    out.mux(packet)
                out.close()
            except Exception as exc:     # encoder missing in this FFmpeg build
                print(f"skip {name}: {exc}")
                continue
            dec, data = _decode_all(path)
            self.assertEqual(data.dtype, np.float32, name)
            self.assertGreater(len(data), rate * 0.8, name)
            info = meta.read_tags(path)
            self.assertGreater(info["duration"], 0.5, name)

    def test_broken_file_does_not_crash(self):
        path = os.path.join(self.tmp, "broken.flac")
        with open(path, "wb") as f:
            f.write(b"fLaC" + os.urandom(5000))
        with self.assertRaises(audio.DecodeError):
            audio.Decoder(path)
        info = meta.read_tags(path)        # must not raise
        self.assertEqual(info["title"], "broken")

    def test_gain_bypass_is_exact(self):
        """At 100 % volume the callback must not touch the samples."""
        eng = audio.AudioEngine.__new__(audio.AudioEngine)
        eng._paused = False
        eng.muted = False
        eng.volume = 1.0
        eng._gain_now = 1.0
        eng._fade_in = False
        eng._cb_rate = 44100
        block = (_signal(44100, 0.05, 16)).astype(np.int16)
        out = block.copy()
        eng._apply_gain(out)
        self.assertTrue(np.array_equal(out, block))


class MetaTests(unittest.TestCase):
    def test_format_label(self):
        self.assertEqual(meta.format_label("FLAC", 96000, 24, 0), "FLAC 24/96")
        self.assertEqual(meta.format_label("FLAC", 44100, 16, 0), "FLAC 16/44.1")
        self.assertEqual(meta.format_label("MP3", 44100, 0, 320000), "MP3 320k")
        self.assertTrue(meta.is_hires(96000, 24))
        self.assertFalse(meta.is_hires(44100, 16))


class TokenAfterGaplessTests(unittest.TestCase):
    def test_engine_speaks_for_the_song_being_heard(self):
        """After a gapless hand-off, pause / resume events must carry the new song's token
        (the player ignores the old one - it then thought the music was still playing)."""
        engine = audio.AudioEngine()
        try:
            engine._paths = {1: "first.flac", 3: "second.flac"}
            engine.token, engine._cur_token = 1, 3
            engine._sync_token()
            self.assertEqual(engine.token, 3)
            engine._cur_token = 99                  # unknown token: leave it alone
            engine._sync_token()
            self.assertEqual(engine.token, 3)
        finally:
            engine.shutdown()

if __name__ == "__main__":
    unittest.main()
