"""Self-test for a built program (the .exe has no Python to run unit tests with).

Start the program with the environment variable T9_SELFTEST=<folder>. It opens
normally, checks codecs, audio devices, image plugins and lossless decoding,
saves a screenshot plus report.json into <folder> and quits (exit code 0 = OK).
build.py runs this automatically on every build.
"""

import json
import os
import tempfile
import traceback

import numpy as np


def _decode_check():
    """Encode a 24-bit FLAC, decode it with the player's decoder, compare bit for bit."""
    import av
    from . import audio
    rate = 96000
    rng = np.random.default_rng(7)
    src = rng.integers(-(2 ** 23), 2 ** 23 - 1, size=(rate // 2, 2), dtype=np.int64)
    path = os.path.join(tempfile.mkdtemp(prefix="t9selftest_"), "check.flac")
    out = av.open(path, "w")
    stream = out.add_stream("flac", rate=rate, layout="stereo")
    stream.format = "s32"
    data = (src << 8).astype(np.int32)
    frame = av.AudioFrame.from_ndarray(data.reshape(1, -1), format="s32", layout="stereo")
    frame.sample_rate = rate
    for packet in list(stream.encode(frame)) + list(stream.encode(None)):
        out.mux(packet)
    out.close()
    dec = audio.Decoder(path)
    blocks = []
    while True:
        got = dec.read()
        if got is None:
            break
        blocks.append(got[0])
    dec.close()
    decoded = np.concatenate(blocks).astype(np.int64) >> 8
    return bool(np.array_equal(decoded, src)) and dec.rate == rate


def run(window, folder):
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QImageReader
    from . import APP_VERSION, audio, paths

    report = {"version": APP_VERSION, "frozen": paths.FROZEN, "checks": {}, "errors": []}
    checks = report["checks"]

    def check(name, fn):
        try:
            checks[name] = fn()
        except Exception:
            checks[name] = False
            report["errors"].append(f"{name}: {traceback.format_exc(limit=3)}")

    formats = {bytes(f).decode() for f in QImageReader.supportedImageFormats()}
    check("image_formats", lambda: all(f in formats for f in ("svg", "jpg", "png", "ico")))
    check("assets", lambda: os.path.isfile(paths.ICON_FILE) and os.path.isfile(paths.LOGO_FILE))
    check("codecs", lambda: __import__("av").codecs_available.issuperset(
        {"flac", "alac", "mp3float", "aac", "opus", "vorbis", "wmav2", "ape", "wavpack", "dsd_lsbf"}))
    check("output_devices", lambda: len(audio.list_output_devices()) > 0)
    check("lossless_decode_24_96", _decode_check)

    def finish():
        try:
            os.makedirs(folder, exist_ok=True)
            window.grab().save(os.path.join(folder, "selftest.png"))
        except Exception:
            report["errors"].append("screenshot failed")
        report["ok"] = all(checks.values()) and not report["errors"]
        with open(os.path.join(folder, "report.json"), "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
        from PySide6.QtWidgets import QApplication
        window.quit()
        QApplication.instance().exit(0 if report["ok"] else 1)

    QTimer.singleShot(2500, finish)
