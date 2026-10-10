"""Playback torture test: many scenarios on generated tones, checking that the player and the engine
always agree and that the position moves exactly when it should. Engine muted - nothing is heard.

    python tools/playback_stress.py      (needs a working audio output, takes about 3 minutes)
"""
import os
import shutil
import sys
import tempfile
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="t9stress_")
os.environ["T9_PLAYER_DATA"] = os.path.join(TMP, "data")
sys.path.insert(0, ROOT)

import av  # noqa: E402
import numpy as np  # noqa: E402
from PySide6.QtCore import QCoreApplication  # noqa: E402

from t9player import audio, library as libmod, paths  # noqa: E402
from t9player.player import Player  # noqa: E402
from t9player.settings import Settings  # noqa: E402

import logging
logging.basicConfig(level=logging.WARNING, format="     log %(name)s: %(message)s")
app = QCoreApplication([])


def tone(name, rate=44100, seconds=20.0, freq=440, fmt="s16", codec="flac", ext="flac"):
    path = os.path.join(TMP, f"{name}.{ext}")
    with av.open(path, "w") as out:
        st = out.add_stream(codec, rate=rate)
        st.layout = "stereo"
        n = int(rate * seconds)
        t = np.arange(n) / rate
        wave = (np.sin(2 * np.pi * freq * t) * 0.3)
        if fmt == "s16":
            data = (wave * 32767).astype(np.int16)
        else:
            data = (wave * 2147483647).astype(np.int32)
        stereo = np.ascontiguousarray(np.vstack([data, data]).T.reshape(1, -1))
        frame = av.AudioFrame.from_ndarray(stereo, format=fmt, layout="stereo")
        frame.rate = rate
        for packet in st.encode(frame):
            out.mux(packet)
        for packet in st.encode(None):
            out.mux(packet)
    return path


files = {
    "a": tone("a_44k", 44100, 20, 440),
    "b": tone("b_44k", 44100, 20, 550),
    "c": tone("c_48k", 48000, 20, 660),              # different rate: gapless must wait for the drain
    "d": tone("d_96k_24", 96000, 20, 330, fmt="s32"),
    "mp3": tone("e_mp3", 44100, 20, 770, fmt="s16", codec="mp3", ext="mp3") if "mp3" in av.codecs_available else None,
}
bad = os.path.join(TMP, "broken.flac")
open(bad, "wb").write(b"not audio at all" * 100)
missing = os.path.join(TMP, "gone.flac")

paths.ensure_dirs()
lib = libmod.Library(paths.LIBRARY_DB)
lib.load()
T = {k: lib.track_for_path(v) for k, v in files.items() if v}
settings = Settings()
p = Player(lib, settings)
p.engine.muted = True
messages = []
p.message.connect(lambda level, text: messages.append((level, text)))

results = []


def pump(sec):
    end = time.perf_counter() + sec
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.005)


def check(name, expect_state=None, moving=None, track=None, allow=()):
    """Settle, then verify the invariants."""
    pump(0.5)
    problems = []
    if p.state != p.engine.state and not (p.engine.state == audio.STATE_STOPPED and p.state == audio.STATE_STOPPED):
        problems.append(f"player says {p.state}, engine says {p.engine.state}")
    if expect_state and p.engine.state != expect_state:
        problems.append(f"expected {expect_state}, engine is {p.engine.state}")
    if track and (p.current is None or p.current.path != T[track].path):
        problems.append(f"expected track {track}, current is {p.current.title if p.current else None}")
    if moving is not None:
        a = p.position()
        pump(0.6)
        b = p.position()
        if moving and b - a < 0.3:
            problems.append(f"position should move but went {a:.2f} -> {b:.2f}")
        if not moving and abs(b - a) > 0.05:
            problems.append(f"position should stand still but went {a:.2f} -> {b:.2f}")
    unexpected = [m for m in messages if m[0] in ("error", "warning") and not any(x in m[1] for x in allow)]
    if unexpected:
        problems.append(f"messages: {unexpected}")
    messages.clear()
    results.append((name, problems))
    print(("  OK   " if not problems else "  FAIL ") + name + ("" if not problems else "  <- " + "; ".join(problems)))


def scenario(title):
    print("\n== " + title)


try:
    scenario("basic")
    p.play_tracks([T["a"], T["b"]], 0)
    check("play starts", audio.STATE_PLAYING, moving=True, track="a")
    p.play_pause()
    check("pause stops the clock", audio.STATE_PAUSED, moving=False)
    p.play_pause()
    check("resume moves again", audio.STATE_PLAYING, moving=True)

    scenario("rapid clicking")
    for _ in range(15):
        p.play_pause()
        pump(0.03)
    check("15 fast toggles end paused or playing consistently")
    if p.engine.state != audio.STATE_PLAYING:
        p.play_pause()
    check("and play still works", audio.STATE_PLAYING, moving=True)

    scenario("long pause")
    p.play_pause()
    pump(5)
    check("after 5 s pause still paused", audio.STATE_PAUSED, moving=False)
    p.play_pause()
    check("resume after a long pause", audio.STATE_PLAYING, moving=True)

    scenario("seeking")
    p.seek(3.0)
    check("seek while playing", audio.STATE_PLAYING, moving=True)
    p.play_pause()
    p.seek(1.0)
    check("seek while paused stays paused", audio.STATE_PAUSED, moving=False)
    if abs(p.position() - 1.0) > 0.3:
        results.append(("paused seek lands on 1.0 s", [f"position {p.position():.2f}"]))
        print(f"  FAIL paused seek lands on 1.0 s  <- {p.position():.2f}")
    p.play_pause()
    check("resume after paused seek", audio.STATE_PLAYING, moving=True)
    for x in (0.5, 4.0, 2.0, 5.0, 1.5):
        p.seek(x)
        pump(0.02)
    check("seek-bar drag (5 quick seeks)", audio.STATE_PLAYING, moving=True)
    p.seek(-5)
    check("negative seek is clamped", audio.STATE_PLAYING, moving=True)

    scenario("gapless hand-off, same format")
    p.play_tracks([T["a"], T["b"]], 0)
    pump(0.5)
    p.seek(T["a"].duration - 1.5)
    pump(2.5)
    check("moved on to the next song", audio.STATE_PLAYING, moving=True, track="b")
    p.play_pause()
    check("pause after gapless", audio.STATE_PAUSED, moving=False)
    p.play_pause()
    check("resume after gapless (the reported bug)", audio.STATE_PLAYING, moving=True, track="b")
    p.seek(0.5)
    check("seek inside the new song", audio.STATE_PLAYING, moving=True, track="b")

    scenario("hand-off to another sample rate (44.1k -> 48k -> 96k/24)")
    p.play_tracks([T["a"], T["c"], T["d"]], 0)
    pump(0.5)
    p.seek(T["a"].duration - 1.0)
    pump(3)
    check("44.1k -> 48k", audio.STATE_PLAYING, moving=True, track="c")
    p.play_pause()
    check("pause on the 48k song", audio.STATE_PAUSED, moving=False)
    p.play_pause()
    p.seek(T["c"].duration - 1.0)
    pump(3)
    check("48k -> 96k/24", audio.STATE_PLAYING, moving=True, track="d")

    scenario("crossfade")
    settings.set("crossfade", 2)
    p.engine.reconfigure(crossfade=2)
    p.play_tracks([T["a"], T["b"], T["a"]], 0)
    pump(0.5)
    p.seek(T["a"].duration - 3.0)
    pump(1.6)
    p.play_pause()
    check("pause in the middle of a crossfade", audio.STATE_PAUSED, moving=False)
    p.play_pause()
    pump(2.5)
    check("crossfade finished after resume", audio.STATE_PLAYING, moving=True, track="b")
    p.seek(T["b"].duration - 2.5)
    pump(1.0)
    p.seek(1.0)
    check("seek during a crossfade", audio.STATE_PLAYING, moving=True)
    settings.set("crossfade", 0)
    p.engine.reconfigure(crossfade=0)
    check("crossfade switched off while playing", audio.STATE_PLAYING, moving=True)

    scenario("skipping")
    p.play_tracks([T["a"], T["b"], T["c"], T["a"], T["b"]], 0)
    pump(0.3)
    for _ in range(4):
        p.next()
        pump(0.02)
    check("4 fast nexts land on the 5th song", audio.STATE_PLAYING, moving=True, track="b")
    p.previous()
    check("previous within 3 s goes back a song", audio.STATE_PLAYING, moving=True, track="a")
    pump(3.2)
    p.previous()
    check("previous after 3 s restarts the song", audio.STATE_PLAYING, moving=True, track="a")
    if p.position() > 1.5:
        results.append(("restart is at the start", [f"{p.position():.1f}"]))

    scenario("end of the queue and repeat")
    p.repeat = "off"
    p.play_tracks([T["a"]], 0)
    pump(0.3)
    p.seek(T["a"].duration - 1.0)
    pump(2.5)
    check("stops at the end of the queue", audio.STATE_STOPPED, allow=("End of the queue",))
    p.play_pause()
    check("play after the end starts again", audio.STATE_PLAYING, moving=True)
    p.repeat = "one"
    p.seek(T["a"].duration - 1.0)
    pump(2.5)
    check("repeat one plays the song again", audio.STATE_PLAYING, moving=True, track="a")
    p.repeat = "all"
    p.play_tracks([T["a"], T["b"]], 1)
    pump(0.3)
    p.seek(T["b"].duration - 1.0)
    pump(2.5)
    check("repeat all wraps to the first song", audio.STATE_PLAYING, moving=True, track="a")
    p.repeat = "off"

    scenario("broken and missing files")
    p.play_tracks([lib.track_for_path(bad), T["b"]], 0)
    pump(1.5)
    check("a broken file is skipped", audio.STATE_PLAYING, moving=True, track="b", allow=("Cannot play",))
    t_missing = lib.track_for_path(files["a"])
    gone = libmod.Track(**{n: getattr(t_missing, n) for n in libmod.Track.__slots__})
    gone.path = missing
    p.play_tracks([gone, T["a"]], 0)
    pump(1.5)
    check("a missing file is skipped", audio.STATE_PLAYING, moving=True, track="a", allow=("Cannot play",))

    scenario("queue edits")
    p.play_tracks([T["a"], T["b"], T["c"], T["a"]], 0)
    pump(0.3)
    p.remove_from_queue(2)
    check("remove an upcoming song", audio.STATE_PLAYING, moving=True, track="a")
    p.jump_to(1)
    check("jump to a song in the queue", audio.STATE_PLAYING, moving=True, track="b")
    p.clear_upcoming()
    check("clear upcoming keeps the current song", audio.STATE_PLAYING, moving=True, track="b")

    scenario("stop, output settings and volume")
    p.stop()
    check("stop", audio.STATE_STOPPED)
    p.play_pause()
    check("play after stop", audio.STATE_PLAYING, moving=True)
    pos = p.position()
    p.engine.reconfigure(buffer_ms=300)
    check("buffer size changed while playing", audio.STATE_PLAYING, moving=True)
    if p.position() < pos:
        results.append(("buffer change keeps the position", [f"{pos:.1f} -> {p.position():.1f}"]))
    p.engine.reconfigure(exclusive=True)
    check("WASAPI Exclusive on while playing", audio.STATE_PLAYING, moving=True,
          allow=("Exclusive mode is not available",))
    p.engine.reconfigure(exclusive=False)
    check("Exclusive off again", audio.STATE_PLAYING, moving=True)
    for v in (0.0, 1.0, 0.3, 0.8):
        p.set_volume(v)
    p.engine.muted = False
    p.engine.muted = True
    check("volume and mute changes", audio.STATE_PLAYING, moving=True)

    scenario("the audio device dies")
    st = p.engine._stream
    st.stop()                           # driver stops the stream while playing
    pump(3)
    check("recovers while playing", audio.STATE_PLAYING, moving=True, allow=("reconnecting",))
    p.play_pause()
    pump(0.5)
    p.engine._stream.stop()             # ... and while paused
    pump(4)
    p.play_pause()
    check("recovers after a dead pause", audio.STATE_PLAYING, moving=True, allow=("reconnecting",))

    scenario("an mp3")
    if "mp3" in T:
        p.play_tracks([T["mp3"], T["a"]], 0)
        check("mp3 plays", audio.STATE_PLAYING, moving=True, track="mp3")
        p.seek(T["mp3"].duration - 1.0)
        pump(2.5)
        check("mp3 -> flac hand-off", audio.STATE_PLAYING, moving=True, track="a")
        p.play_pause()
        check("pause", audio.STATE_PAUSED, moving=False)
        p.play_pause()
        check("resume", audio.STATE_PLAYING, moving=True)
except Exception:
    traceback.print_exc()
    results.append(("script", ["crashed"]))
finally:
    p.shutdown()
    failed = [r for r in results if r[1]]
    print(f"\n{len(results) - len(failed)} / {len(results)} checks passed")
    for name, problems in failed:
        print("FAILED:", name, problems)
    shutil.rmtree(TMP, ignore_errors=True)
