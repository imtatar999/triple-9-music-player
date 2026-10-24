"""Volume normalization: how loud each song is, and how much to turn it up or down.

Loudness is measured like Spotify / ReplayGain 2.0 do it (EBU R128 integrated loudness, LUFS) with
FFmpeg's ebur128 filter, about half a second per song. ReplayGain tags already in a file are used
instead when there are any (no decoding needed).

Every song is brought to TARGET_LUFS (Spotify's "normal" level). Turning a song up never pushes its
loudest sample past full scale, so normalization cannot add distortion.
"""

import math
import os
import re

from .avcompat import open_av

TARGET_LUFS = -14.0
RG_REFERENCE = -18.0         # ReplayGain 2.0 gains are relative to -18 LUFS
MAX_BOOST_DB = 10.0
HEADROOM = 0.989             # highest peak a boost may reach (-0.1 dBFS)


def _float(text):
    m = re.search(r"[-+]?\d+(?:[.,]\d+)?", str(text))
    return float(m.group(0).replace(",", ".")) if m else None


def read_tags(path):
    """ReplayGain from the file's tags -> (track_lufs, track_peak) or None."""
    try:
        import mutagen
        f = mutagen.File(path)
    except Exception:
        return None
    if f is None or f.tags is None:
        return None
    gain = peak = None
    try:
        items = list(f.tags.items())
    except Exception:
        return None
    for key, value in items:
        k = str(key).lower()
        if k.endswith("replaygain_track_gain"):
            gain = _float(getattr(value, "text", [value])[0] if hasattr(value, "text") else
                          (value[0] if isinstance(value, list) else value))
        elif k.endswith("replaygain_track_peak"):
            peak = _float(getattr(value, "text", [value])[0] if hasattr(value, "text") else
                          (value[0] if isinstance(value, list) else value))
        elif k == "r128_track_gain" and gain is None:        # Opus: Q7.8 dB relative to -23 LUFS
            v = _float(value[0] if isinstance(value, list) else value)
            if v is not None:
                gain = v / 256.0 + (RG_REFERENCE - -23.0)
    if gain is None or not -40.0 < gain < 40.0:
        return None
    return RG_REFERENCE - gain, (peak if peak and peak > 0 else 1.0)


def measure(path, cancel=None):
    """Decode the song and measure it -> (integrated LUFS, sample peak) or None."""
    import av
    try:
        container = open_av(path)
    except Exception:
        return None
    try:
        if not container.streams.audio:
            return None
        stream = container.streams.audio[0]
        graph = av.filter.Graph()
        src = graph.add_abuffer(template=stream)
        meter = graph.add("ebur128", "metadata=1:peak=sample")
        sink = graph.add("abuffersink")
        src.link_to(meter)
        meter.link_to(sink)
        graph.configure()
        last = {}

        def drain():
            nonlocal last
            while True:
                try:
                    out = graph.pull()
                except (av.error.BlockingIOError, av.error.EOFError):
                    return
                last = out.metadata

        for packet in container.demux(stream):
            if cancel is not None and cancel.is_set():
                return None
            try:
                frames = packet.decode()
            except av.error.EOFError:
                break
            except (av.error.FFmpegError, ValueError):
                continue                      # a damaged spot: skip it like the player does
            for frame in frames:
                frame.pts = None              # the meter does not need timestamps (and broken ones upset it)
                graph.push(frame)
                drain()
        lufs = _float(last.get("lavfi.r128.I", "")) if last else None
        peak = _float(last.get("lavfi.r128.sample_peak", "")) if last else None
        if lufs is None or lufs <= -69.0:      # silence: nothing to normalize
            return None
        return lufs, (peak if peak and peak > 0 else 1.0)
    except Exception:
        return None
    finally:
        container.close()


def album_lufs(values):
    """Loudness of an album from its songs' loudness (energy average)."""
    values = [v for v in values if v is not None]
    if not values:
        return None
    return 10.0 * math.log10(sum(10.0 ** (v / 10.0) for v in values) / len(values))


def gain_for(lufs, peak):
    """Linear factor that brings a song of this loudness to the target without clipping."""
    if lufs is None:
        return 1.0
    db = min(TARGET_LUFS - lufs, MAX_BOOST_DB)
    factor = 10.0 ** (db / 20.0)
    if factor > 1.0 and peak:
        factor = max(1.0, min(factor, HEADROOM / peak))
    return factor


def file_key(path):
    try:
        st = os.stat(path)
        return st.st_mtime, st.st_size
    except OSError:
        return None
