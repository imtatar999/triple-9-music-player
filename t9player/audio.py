"""Audio engine: FFmpeg (PyAV) decoding + PortAudio/WASAPI output.

Design goals
  * Lossless: samples are delivered in the decoder's native integer format and
    native sample rate. With WASAPI exclusive mode and 100 % volume nothing in
    the chain changes a single bit (no resampling, no dither, no mixing).
  * Never stutter: decoding runs ~2 s ahead in its own thread; the PortAudio
    callback only copies ready-made numpy blocks.
  * Never crash: every thread catches its own errors and reports them as
    events; the UI polls `poll_events()` from its timer.
  * Gapless: the next track is decoded into the same buffer when its format
    matches, so albums play without a gap.

Thread model
  engine thread  - owns the decoder and the output stream (open/close/seek)
  audio callback - PortAudio thread, copies samples, never blocks for long
  caller (UI)    - only sends commands through a queue and reads snapshots
"""

import collections
import queue
import sys
import threading
import time
import logging
import os
import traceback

import numpy as np

from .i18n import tr

try:
    import sounddevice as sd
except Exception:  # pragma: no cover - reported in the UI
    sd = None

_log = logging.getLogger("t9player.audio")

STATE_STOPPED = "stopped"
STATE_PLAYING = "playing"
STATE_PAUSED = "paused"

_FADE_SECONDS = 0.012
_STALL_SECONDS = 2.0        # a stream that has not asked for audio for this long is dead
_AHEAD_SECONDS = 2.0


def _com_init():
    """WASAPI streams can only start on a thread that initialised COM."""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.ole32.CoInitializeEx(None, 0)   # COINIT_MULTITHREADED
        except Exception:
            pass


def volume_to_gain(volume):
    """Perceptual volume curve: slider 0..1 -> linear gain."""
    v = min(1.0, max(0.0, float(volume)))
    return v * v


class _Chunk:
    __slots__ = ("data", "t0", "token", "eof", "rate")

    def __init__(self, data, t0, token, rate, eof=False):
        self.data = data
        self.t0 = t0
        self.token = token
        self.rate = rate
        self.eof = eof


# --------------------------------------------------------------------------- decoder

_DTYPES = {
    "s16": np.int16, "s16p": np.int16,
    "s32": np.int32, "s32p": np.int32,
    "flt": np.float32, "fltp": np.float32,
}


class DecodeError(Exception):
    pass


class _ArrayFrame:
    """A block that is already converted and trimmed (after an exact seek)."""
    __slots__ = ("arr",)

    def __init__(self, arr):
        self.arr = arr


class Decoder:
    """Opens one file and yields stereo numpy blocks in one fixed dtype.

    16-bit sources stay int16, 24/32-bit sources stay int32 (FFmpeg stores
    24-bit samples left-aligned in 32 bits, which PortAudio passes through
    unchanged), lossy codecs decode to float32.
    """

    def __init__(self, path, start=0.0):
        import av
        self._av = av
        self.path = path
        try:
            self.container = av.open(path, metadata_errors="ignore")
        except Exception as exc:
            raise DecodeError(tr("Cannot open file: {error}", error=exc)) from exc
        if not self.container.streams.audio:
            self.close()
            raise DecodeError(tr("File has no audio stream"))
        self.stream = self.container.streams.audio[0]
        self.time_base = self.stream.time_base
        self._frames = self._frame_iter()
        self._pending = []
        self._errors = 0
        self.eof = False
        self.resampler = None
        self.target_rate = None
        self.t = 0.0
        self.duration = 0.0
        if self.container.duration:
            self.duration = self.container.duration / 1_000_000.0
        elif self.stream.duration and self.time_base:
            self.duration = float(self.stream.duration * self.time_base)
        first = self._next_frame()
        if first is None:
            self.close()
            raise DecodeError(tr("No decodable audio in this file"))
        self._setup_format(first)
        if start > 0.05:
            self.seek(start)
        else:
            self._pending.append(first)

    # -- format ----------------------------------------------------------------
    def _setup_format(self, frame):
        fmt = frame.format.name
        cc = self.stream.codec_context
        self.src_rate = int(frame.sample_rate or cc.sample_rate or 44100)
        self.rate = self.src_rate
        self.src_channels = len(frame.layout.channels)
        self.bits = int(getattr(cc, "bits_per_raw_sample", 0) or 0)
        if fmt in ("s16", "s16p"):
            self.bits = self.bits or 16
        elif fmt in ("s32", "s32p") and not self.bits:
            self.bits = 32
        self.dtype = _DTYPES.get(fmt)
        self.native = self.dtype is not None and self.src_channels in (1, 2)
        self._int_scale = None
        if not self.native:
            # exotic sample formats (u8, dbl, s64) or surround -> float stereo
            self.dtype = np.float32
            self.bits = 0
            self._make_resampler(self.src_rate)

    def force_float(self):
        """Deliver float32 in -1..1 (crossfade mixes two songs, so it cannot stay bit-exact)."""
        if self.dtype == np.int16:
            self._int_scale = 1.0 / 32768.0
        elif self.dtype == np.int32:
            self._int_scale = 1.0 / 2147483648.0
        self.dtype = np.float32
        if self.resampler is not None:
            self._make_resampler(self.rate)

    def _make_resampler(self, rate):
        fmt = {np.int16: "s16", np.int32: "s32"}.get(self.dtype, "flt")
        self.resampler = self._av.AudioResampler(format=fmt, layout="stereo", rate=rate)
        self.rate = rate

    def set_target_rate(self, rate):
        """Used only when the output cannot run at the file's own rate."""
        if rate and rate != self.rate:
            self.target_rate = rate
            self._make_resampler(rate)

    @property
    def is_float(self):
        return self.dtype == np.float32

    # -- decoding ----------------------------------------------------------------
    def _frame_iter(self):
        av = self._av
        for packet in self.container.demux(self.stream):
            try:
                frames = packet.decode()
            except av.error.EOFError:
                return
            except (av.error.FFmpegError, ValueError):
                self._errors += 1
                if self._errors > 200:
                    return
                continue
            self._errors = 0
            for frame in frames:
                yield frame

    def _next_frame(self):
        for _ in range(3):
            try:
                return next(self._frames)
            except StopIteration:
                return None
            except Exception:
                # a damaged container: restart demuxing after the broken spot
                self._errors += 1
                if self._errors > 200:
                    return None
                self._frames = self._frame_iter()
        return None

    def _to_array(self, frame):
        if isinstance(frame, _ArrayFrame):
            return frame.arr
        arr = frame.to_ndarray()
        if frame.format.is_planar:
            arr = arr.T
        else:
            arr = arr.reshape(-1, len(frame.layout.channels))
        if arr.shape[1] == 1:
            arr = np.repeat(arr, 2, axis=1)       # exact mono -> stereo
        if arr.dtype != self.dtype:
            if self._int_scale is not None and arr.dtype.kind == "i":
                arr = arr.astype(np.float32) * np.float32(self._int_scale)
            else:
                arr = arr.astype(self.dtype)
        return np.ascontiguousarray(arr)

    def _convert(self, frame):
        if self.resampler is None:
            return self._to_array(frame)
        if isinstance(frame, _ArrayFrame):
            return None
        out = self.resampler.resample(frame)
        arrays = [self._to_array(f) for f in out]
        arrays = [a for a in arrays if len(a)]
        if not arrays:
            return None
        return arrays[0] if len(arrays) == 1 else np.concatenate(arrays)

    def read(self):
        """Return (array[frames, 2], t0) or None at end of stream."""
        while True:
            frame = self._pending.pop(0) if self._pending else self._next_frame()
            if frame is None:
                data = None
                if self.resampler is not None and not self.eof:
                    try:
                        arrays = [self._to_array(f) for f in self.resampler.resample(None)]
                        arrays = [a for a in arrays if len(a)]
                        data = np.concatenate(arrays) if arrays else None
                    except Exception:
                        data = None
                self.eof = True
                if data is None:
                    return None
            else:
                try:
                    data = self._convert(frame)
                except Exception:
                    continue
                if data is None or not len(data):
                    continue
            t0 = self.t
            self.t += len(data) / self.rate
            return data, t0

    def seek(self, seconds):
        seconds = max(0.0, float(seconds))
        self._pending = []
        self.eof = False
        if self.resampler is not None:
            self._make_resampler(self.target_rate or self.src_rate)
        start_pts = self.stream.start_time or 0
        try:
            ts = int(seconds / self.time_base) + start_pts
            self.container.seek(ts, stream=self.stream, backward=True, any_frame=False)
        except Exception:
            try:
                self.container.seek(0)
            except Exception:
                pass
        self._frames = self._frame_iter()
        # decode forward and trim to the exact sample
        while True:
            frame = self._next_frame()
            if frame is None:
                self.t = seconds
                return
            if frame.pts is None:
                self._pending.append(frame)
                self.t = seconds
                return
            rate = frame.sample_rate or self.src_rate
            f_start = float((frame.pts - start_pts) * self.time_base)
            if f_start + frame.samples / rate <= seconds:
                continue
            skip = int(round((seconds - f_start) * rate))
            if skip > 0 and self.resampler is None:
                self._pending.append(_ArrayFrame(self._to_array(frame)[skip:]))
                self.t = seconds
            else:
                self._pending.append(frame)
                self.t = max(0.0, f_start)
            return

    def close(self):
        try:
            self.container.close()
        except Exception:
            pass


# --------------------------------------------------------------------------- devices

def wasapi_index():
    if sd is None:
        return None
    try:
        for i, api in enumerate(sd.query_hostapis()):
            if "WASAPI" in api["name"]:
                return i
    except Exception:
        return None
    return None


def list_output_devices():
    """[(name, device_index)] for WASAPI outputs (falls back to all outputs)."""
    if sd is None:
        return []
    out = []
    try:
        api = wasapi_index()
        for idx, dev in enumerate(sd.query_devices()):
            if dev["max_output_channels"] < 1:
                continue
            if api is not None and dev["hostapi"] != api:
                continue
            out.append((dev["name"], idx))
    except Exception:
        return []
    return out


def resolve_device(name):
    """Device index for a stored name; the default WASAPI output when missing."""
    if sd is None:
        return None
    if name:
        for dev_name, idx in list_output_devices():
            if dev_name == name:
                return idx
    try:
        api = wasapi_index()
        if api is not None:
            idx = sd.query_hostapis(api)["default_output_device"]
            if idx is not None and idx >= 0:
                return idx
        return sd.default.device[1]
    except Exception:
        return None


class DefaultOutputWatch:
    """Id of Windows' default playback device (Core Audio, plain ctypes - no extra packages).

    Polled by the engine thread (which has COM initialised); cheap enough to ask once a second."""

    _CLSID = "{BCDE0395-E52F-467C-8E3D-C4579291692E}"   # MMDeviceEnumerator
    _IID = "{A95664D2-9614-4F35-A746-DE8DB63617E6}"     # IMMDeviceEnumerator

    def __init__(self):
        self._enum = None
        self.broken = not sys.platform.startswith("win")

    def _guid(self, text):
        import ctypes

        class GUID(ctypes.Structure):
            _fields_ = [("d1", ctypes.c_uint32), ("d2", ctypes.c_uint16), ("d3", ctypes.c_uint16),
                        ("d4", ctypes.c_ubyte * 8)]
        g = GUID()
        ctypes.oledll.ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(g))
        return g

    def _method(self, obj, index, *argtypes):
        import ctypes
        vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        return ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *argtypes)(vtable[index])

    def current_id(self):
        """The default output's id, or None when it cannot be read (no device, not Windows ...)."""
        if self.broken:
            return None
        import ctypes
        try:
            if self._enum is None:
                enum = ctypes.c_void_p()
                ctypes.oledll.ole32.CoCreateInstance(ctypes.byref(self._guid(self._CLSID)), None, 1 | 4 | 16,
                                                     ctypes.byref(self._guid(self._IID)), ctypes.byref(enum))
                self._enum = enum
            device = ctypes.c_void_p()
            # IMMDeviceEnumerator::GetDefaultAudioEndpoint(eRender, eMultimedia, &device)
            self._method(self._enum, 4, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))(
                self._enum, 0, 1, ctypes.byref(device))
            try:
                text = ctypes.c_wchar_p()
                self._method(device, 5, ctypes.POINTER(ctypes.c_wchar_p))(device, ctypes.byref(text))   # GetId
                value = text.value
                ctypes.windll.ole32.CoTaskMemFree(text)
                return value
            finally:
                self._method(device, 2)(device)                                                       # Release
        except OSError:
            return None            # e.g. no playback device at all right now
        except Exception:
            self.broken = True
            return None


def refresh_devices():
    """Make PortAudio see the current devices and Windows' current default (it caches both at start)."""
    if sd is None:
        return
    try:
        sd._terminate()
    except Exception:
        pass
    try:
        sd._initialize()
    except Exception:
        pass


# --------------------------------------------------------------------------- engine

class AudioEngine:
    def __init__(self):
        self._cmd = queue.Queue()
        self.events = queue.SimpleQueue()
        self._lock = threading.Lock()
        self._buf = collections.deque()
        self._buf_frames = 0
        self._off = 0
        # settings (plain attributes are atomic to read in CPython)
        self.volume = 0.8
        self.muted = False
        self.exclusive = False
        self.device_name = ""
        self.buffer_ms = 150
        self.gapless = True
        self.crossfade = 0          # seconds; > 0 mixes the end of a song into the next one
        self._xf = None             # running crossfade state
        # written by the audio callback
        self._cur_token = None      # token of the samples going out now
        self._cb_pos = 0.0          # track seconds of the first sample of the last block
        self._cb_end = 0.0          # track seconds after the last real sample written
        self._cb_perf = 0.0
        self._cb_lag = 0.0          # seconds from write to the speaker
        self._cb_rate = 44100
        self._gain_now = 0.0
        self._paused = True
        self._fade_in = False
        self._last_cb_perf = 0.0
        self._priming = False       # loading a track: silence is expected, not an underrun
        self.underruns = 0
        # owned by the engine thread
        self.state = STATE_STOPPED
        self.token = None
        self.duration = 0.0
        self.output_info = {}
        self._stream = None
        self._stream_key = None
        self._decoder = None
        self._dec_token = None
        self._next = None           # (path, token)
        self._seek_target = None
        self._seek_perf = 0.0
        self._wait_drain = False    # format change: wait until the old track drained
        self._held_decoder = None   # (decoder, token) of that next track
        self._paths = {}            # token -> path, to reopen a track on our own
        self._default_watch = DefaultOutputWatch()
        self._default_id = None     # Windows' default output when we last looked
        self._default_check = 0.0
        self._recoveries = []       # times of recent reconnects (to stop endless retrying)
        self._underruns_logged = 0
        self._next_health_log = 0.0
        self.heartbeat = time.perf_counter()     # watched by diagnostics.Watchdog
        self.thread_id = None
        self._alive = True
        self._thread = threading.Thread(target=self._run, name="T9AudioEngine", daemon=True)
        self._thread.start()

    # ------------------------------------------------------------------ public API
    def load(self, path, token, start=0.0, paused=False):
        if start > 0:
            self._seek_target = float(start)
            self._seek_perf = time.perf_counter()
        self._cmd.put(("load", path, token, float(start), bool(paused)))

    def set_next(self, path, token):
        self._cmd.put(("next", path, token))

    def seek(self, seconds):
        self._seek_target = max(0.0, float(seconds))
        self._seek_perf = time.perf_counter()
        self._cmd.put(("seek", self._seek_target))

    def pause(self):
        self._cmd.put(("pause",))

    def resume(self):
        self._cmd.put(("resume",))

    def stop(self):
        self._cmd.put(("stop",))

    def reconfigure(self, device_name=None, exclusive=None, buffer_ms=None, crossfade=None):
        self._cmd.put(("config", device_name, exclusive, buffer_ms, crossfade))

    def shutdown(self):
        self._alive = False
        self._cmd.put(("quit",))
        self._thread.join(timeout=2.0)

    def position(self):
        """Seconds into the track that the listener hears right now."""
        if self._seek_target is not None:
            return self._seek_target
        if self.state == STATE_STOPPED and self._decoder is None:
            return max(0.0, self._cb_end)
        if self._paused or self.state == STATE_PAUSED:
            return max(0.0, self._cb_end)
        heard = self._cb_pos + (time.perf_counter() - self._cb_perf) - self._cb_lag
        return max(0.0, min(heard, self._cb_end))

    def poll_events(self):
        out = []
        while True:
            try:
                out.append(self.events.get_nowait())
            except queue.Empty:
                return out

    # ------------------------------------------------------------------ callback
    def _callback(self, out, frames, time_info, status):
        try:
            self._fill(out, frames, time_info)
        except Exception:
            out.fill(0)
            self._post("error", None, "Audio callback: " + traceback.format_exc(limit=2))

    def _fill(self, out, frames, time_info):
        now = time.perf_counter()
        self._last_cb_perf = now
        if self._paused and self._gain_now <= 0.0:
            out.fill(0)
            return
        try:
            lag = float(time_info.outputBufferDacTime - time_info.currentTime)
            if not 0.0 <= lag < 2.0:
                raise ValueError
        except Exception:
            stream = self._stream
            lag = float(stream.latency) if stream is not None else 0.1
        written = 0
        block_pos = None
        with self._lock:
            while written < frames and self._buf:
                chunk = self._buf[0]
                if chunk.eof:
                    self._buf.popleft()
                    self._post("eof", chunk.token)
                    break
                if chunk.token != self._cur_token:
                    self._cur_token = chunk.token
                    self._post("started", chunk.token)
                if block_pos is None:
                    block_pos = chunk.t0 + self._off / chunk.rate
                    self._cb_rate = chunk.rate
                take = min(frames - written, len(chunk.data) - self._off)
                out[written:written + take] = chunk.data[self._off:self._off + take]
                written += take
                self._off += take
                self._buf_frames -= take
                self._cb_end = chunk.t0 + self._off / chunk.rate
                if self._off >= len(chunk.data):
                    self._buf.popleft()
                    self._off = 0
        if written < frames:
            out[written:].fill(0)
            if (written == 0 and not self._paused and self._seek_target is None and not self._priming
                    and not self._wait_drain and self._decoder is not None):
                self.underruns += 1
        if block_pos is not None:
            self._cb_pos = block_pos
            self._cb_perf = now
            self._cb_lag = lag
            if self._seek_target is not None and now - self._seek_perf > 0.05:
                self._seek_target = None
        self._apply_gain(out)

    def _apply_gain(self, out):
        target = 0.0 if (self._paused or self.muted) else volume_to_gain(self.volume)
        start = 0.0 if self._fade_in else self._gain_now
        self._fade_in = False
        if start == 1.0 and target == 1.0:
            return  # bit-perfect path: samples untouched
        self._gain_now = target
        if start == target:
            gain = target
        else:
            n = len(out)
            ramp = max(1, min(n, int(self._cb_rate * _FADE_SECONDS)))
            gain = np.full(n, target, dtype=np.float64)
            gain[:ramp] = np.linspace(start, target, ramp, endpoint=False)
            gain = gain[:, None]
        if out.dtype == np.float32:
            out *= np.float32(gain) if np.isscalar(gain) else gain.astype(np.float32)
        else:
            info = np.iinfo(out.dtype)
            scaled = np.rint(out * gain)
            np.clip(scaled, info.min, info.max, out=scaled)
            out[:] = scaled

    def _post(self, kind, token, payload=None):
        self.events.put((kind, token, payload))

    # ------------------------------------------------------------------ engine thread
    @property
    def alive(self):
        return self._alive

    def _run(self):
        _com_init()
        self.thread_id = threading.get_ident()
        while self._alive:
            self.heartbeat = time.perf_counter()
            try:
                try:
                    cmd = self._cmd.get(timeout=0.005 if self._needs_data() else 0.04)
                except queue.Empty:
                    cmd = None
                if cmd is not None:
                    self._handle(cmd)
                    continue
                self._service()
            except Exception:
                _log.exception("engine error")
                self._post("error", self._dec_token, "Engine: " + traceback.format_exc(limit=3))
                time.sleep(0.05)
        self._close_stream()
        self._close_decoder()

    def _remember(self, token, path):
        self._paths[token] = path
        if len(self._paths) > 64:
            for key in list(self._paths)[:-32]:
                self._paths.pop(key, None)

    def _newer_queued(self, kind):
        with self._cmd.mutex:
            return any(c[0] == kind for c in self._cmd.queue)

    def _handle(self, cmd):
        kind = cmd[0]
        if kind != "next" and not (kind in ("seek", "load") and self._newer_queued(kind)):
            _log.info("cmd %s %s (state %s, at %.1f s)", kind,
                      " ".join(os.path.basename(str(c)) if isinstance(c, str) else str(c) for c in cmd[1:3]),
                      self.state, self.position())
        if kind == "load":
            _, path, token, start, paused = cmd
            self._remember(token, path)
            if not self._newer_queued("load"):      # fast skipping: only the newest matters
                self._load(path, token, start, paused)
        elif kind == "next":
            self._next = (cmd[1], cmd[2]) if cmd[1] else None
            if self._next:
                self._remember(cmd[2], cmd[1])
        elif kind == "seek":
            if not self._newer_queued("seek"):      # seek-bar dragging: only the last one
                self._do_seek(cmd[1])
        elif kind == "pause":
            if self.state == STATE_PLAYING:
                self._paused = True
                self.state = STATE_PAUSED
                self._post("state", self.token, STATE_PAUSED)
        elif kind == "resume":
            if self.state == STATE_PAUSED:
                if not self._stream_ok():
                    # the device went away / fell asleep during the pause: start over on a fresh stream
                    self._recover("the output was not running when playback resumed", paused=False)
                    return
                self._paused = False
                self.state = STATE_PLAYING
                self._post("state", self.token, STATE_PLAYING)
        elif kind == "stop":
            self._stop()
        elif kind == "config":
            _, device_name, exclusive, buffer_ms, crossfade = cmd
            changed = False
            if crossfade is not None and int(crossfade) != self.crossfade:
                self.crossfade, changed = int(crossfade), True
            if device_name is not None and device_name != self.device_name:
                self.device_name, changed = device_name, True
            if exclusive is not None and exclusive != self.exclusive:
                self.exclusive, changed = exclusive, True
            if buffer_ms is not None and buffer_ms != self.buffer_ms:
                self.buffer_ms, changed = buffer_ms, True
            if changed:
                pos = self.position()
                active = self.state != STATE_STOPPED
                self._close_stream()
                if active:
                    self._reopen(pos, paused=self.state == STATE_PAUSED)
        elif kind == "quit":
            self._alive = False

    def _needs_data(self):
        dec = self._decoder
        if dec is None or self._wait_drain:
            return False
        return self._buf_frames < dec.rate * _AHEAD_SECONDS

    def _follow_system_default(self):
        """'System default' output: when Windows switches the default device, move the music there."""
        now = time.perf_counter()
        if self.device_name or now < self._default_check:
            return
        self._default_check = now + 1.0
        current = self._default_watch.current_id()
        if current is None:
            return
        previous, self._default_id = self._default_id, current
        if previous is None or previous == current:
            return
        pos = self.position()
        active = self.state != STATE_STOPPED
        paused = self.state == STATE_PAUSED
        self._close_stream()
        refresh_devices()
        if active:
            self._reopen(pos, paused=paused)
        name = self.output_info.get("device") if active else None
        self._post("info", self.token, tr("Now playing on {device}", device=name) if name
                   else tr("Switched to the new default playback device"))

    def _service(self):
        self._follow_system_default()
        for _ in range(12):
            if not self._needs_data() or not self._decode_one():
                break
        if self._wait_drain and not self._buf:
            self._wait_drain = False
            held, self._held_decoder = self._held_decoder, None
            if held is not None:
                self._install_decoder(held[0], held[1], play=not self._paused)
        now = time.perf_counter()
        # watchdog: device unplugged / driver stalled while playing
        if (self.state == STATE_PLAYING and self._stream is not None and self._last_cb_perf > 0
                and now - self._last_cb_perf > 1.5):
            self._recover("the output stopped asking for audio while playing", paused=False)
            return
        # the same during a pause: forget the dead stream, resume will open a new one
        if (self.state == STATE_PAUSED and self._stream is not None and self._last_cb_perf > 0
                and now - self._last_cb_perf > _STALL_SECONDS + 1.0):
            _log.warning("output stream died during the pause (no callback for %.1f s) - closed it",
                         now - self._last_cb_perf)
            self._close_stream()
        if now >= self._next_health_log:
            self._next_health_log = now + 30.0
            if self.underruns > self._underruns_logged:
                _log.warning("%d buffer underrun(s) in the last 30 s", self.underruns - self._underruns_logged)
                self._underruns_logged = self.underruns

    def _recover(self, reason, paused):
        """Reconnect to the audio device on a brand-new stream, at the same place in the song.
        Gives up (and says so) when the device keeps failing, instead of retrying forever."""
        now = time.perf_counter()
        self._recoveries = [t for t in self._recoveries if now - t < 20.0] + [now]
        pos = self.position()
        _log.warning("audio recovery #%d: %s (at %.1f s, device %r)", len(self._recoveries), reason, pos,
                     self.output_info.get("device"))
        self._close_stream()
        refresh_devices()
        if len(self._recoveries) > 3:
            _log.error("audio device keeps failing - stopped retrying, waiting for the user")
            self._recoveries.clear()
            self._paused = True
            self.state = STATE_PAUSED
            self._seek_target = None
            self._post("error", self.token, tr("The audio device is not responding. Check your speakers or "
                                               "headphones and press play to try again."))
            self._post("state", self.token, STATE_PAUSED)
            return
        self._post("warning", self.token, tr("Audio device stopped responding - reconnecting"))
        self._reopen(pos, paused=paused)

    def _open(self, path, start=0.0):
        dec = Decoder(path, start=start)
        if self.crossfade > 0:
            dec.force_float()
        return dec

    def _xfade_due(self, dec):
        if self.crossfade <= 0 or self._xf is not None or self._next is None or dec.duration <= 0:
            return False
        fade = min(float(self.crossfade), dec.duration / 3.0)
        return dec.t >= dec.duration - fade

    def _start_xfade(self, dec):
        path, token = self._next
        self._next = None
        try:
            nxt = self._open(path)
        except Exception as exc:
            self._post("error", token, str(exc))
            return
        if nxt.dtype != np.float32:
            nxt.force_float()
        if nxt.rate != dec.rate:
            nxt.set_target_rate(dec.rate)
        frames = max(1, int(max(0.5, dec.duration - dec.t) * dec.rate))
        self._xf = {"next": nxt, "token": token, "length": frames, "pos": 0,
                    "a": np.zeros((0, 2), np.float32), "b": np.zeros((0, 2), np.float32),
                    "b_t": 0.0, "a_done": False}

    def _xfade_step(self, dec):
        """Mix one block of the outgoing song (a) with the incoming one (b), equal power."""
        xf = self._xf
        nxt = xf["next"]
        want = 4096
        while len(xf["a"]) < want and not xf["a_done"]:
            got = dec.read()
            if got is None:
                xf["a_done"] = True
            else:
                xf["a"] = np.concatenate([xf["a"], got[0].astype(np.float32, copy=False)])
        while len(xf["b"]) < want:
            got = nxt.read()
            if got is None:
                break
            if not len(xf["b"]):
                xf["b_t"] = got[1]
            xf["b"] = np.concatenate([xf["b"], got[0]])
        a, b = xf["a"], xf["b"]
        n = min(len(a), len(b)) if not xf["a_done"] else len(b)
        if n <= 0 and not len(b):
            self._finish_xfade(dec)
            return True
        n = max(1, min(n, want))
        x = (xf["pos"] + np.arange(n, dtype=np.float32)) / xf["length"]
        x = np.clip(x, 0.0, 1.0)
        gain_a = np.cos(x * (np.pi / 2))[:, None]
        gain_b = np.sin(x * (np.pi / 2))[:, None]
        part_b = b[:n]
        part_a = a[:n] if len(a) >= n else np.concatenate([a, np.zeros((n - len(a), 2), np.float32)])
        mixed = (part_a * gain_a + part_b * gain_b).astype(np.float32)
        t0 = xf["b_t"]
        xf["a"], xf["b"] = a[n:], b[n:]
        xf["b_t"] = t0 + n / dec.rate
        xf["pos"] += n
        with self._lock:
            self._buf.append(_Chunk(mixed, t0, xf["token"], dec.rate))
            self._buf_frames += n
        if xf["pos"] >= xf["length"] or (xf["a_done"] and not len(xf["a"])):
            self._finish_xfade(dec)
        return True

    def _finish_xfade(self, dec):
        xf, self._xf = self._xf, None
        nxt = xf["next"]
        dec.close()
        self._decoder, self._dec_token = nxt, xf["token"]
        self.duration = nxt.duration
        if len(xf["b"]):
            with self._lock:
                self._buf.append(_Chunk(xf["b"], xf["b_t"], xf["token"], nxt.rate))
                self._buf_frames += len(xf["b"])
        self._post("loaded", xf["token"], {"duration": nxt.duration, "output": dict(self.output_info), "gapless": True})

    def _decode_one(self):
        dec = self._decoder
        if self._xf is not None:
            try:
                return self._xfade_step(dec)
            except Exception as exc:
                self._post("warning", self._dec_token, tr("Crossfade problem: {error}", error=exc))
                self._drop_xfade()
        elif self._xfade_due(dec):
            self._start_xfade(dec)
            if self._xf is not None:
                return True
        try:
            got = dec.read()
        except Exception as exc:
            self._post("warning", self._dec_token, tr("Decoding error: {error}", error=exc))
            got = None
        if got is not None:
            data, t0 = got
            with self._lock:
                self._buf.append(_Chunk(data, t0, self._dec_token, dec.rate))
                self._buf_frames += len(data)
            return True
        # end of this file
        finished = self._dec_token
        nxt = self._next if self.gapless else None
        self._next = None
        if nxt is not None:
            path, token = nxt
            try:
                new_dec = self._open(path)
            except Exception as exc:
                self._post("error", token, str(exc))
                new_dec = None
            if new_dec is not None:
                dec.close()
                if self._compatible(new_dec):
                    self._decoder, self._dec_token = new_dec, token
                    self.duration = new_dec.duration
                    self._post("loaded", token, {"duration": new_dec.duration, "output": dict(self.output_info), "gapless": True})
                    return True
                # different sample rate / format: let the current track finish first
                self._decoder = None
                self._held_decoder = (new_dec, token)
                self._wait_drain = True
                return False
        with self._lock:
            self._buf.append(_Chunk(None, dec.t, finished, dec.rate, eof=True))
        dec.close()
        self._decoder = None
        return False

    def _compatible(self, new_dec):
        if self._stream is None or self._stream_key is None:
            return False
        _, rate, dtype, _, resampled = self._stream_key
        if np.dtype(new_dec.dtype).str != dtype:
            return False
        if new_dec.rate != rate:
            if not resampled:
                return False
            new_dec.set_target_rate(rate)
        return True

    # -- load / seek / stop -------------------------------------------------------
    def _clear_buffer(self):
        with self._lock:
            self._buf.clear()
            self._buf_frames = 0
            self._off = 0

    def _drop_xfade(self):
        if self._xf is not None:
            self._xf["next"].close()
            self._xf = None

    def _close_decoder(self):
        self._drop_xfade()
        if self._decoder is not None:
            self._decoder.close()
        if self._held_decoder is not None:
            self._held_decoder[0].close()
        self._decoder = None
        self._held_decoder = None
        self._wait_drain = False

    def _load(self, path, token, start, paused):
        self._close_decoder()
        self._clear_buffer()
        self._next = None
        self.token = token
        try:
            dec = self._open(path, start)
        except Exception as exc:
            self._seek_target = None
            self._cur_token = None
            self.state = STATE_STOPPED
            self._paused = True
            self._post("error", token, str(exc))
            return
        self._install_decoder(dec, token, play=not paused)

    def _install_decoder(self, dec, token, play):
        self._priming = True
        try:
            self._install(dec, token, play)
        finally:
            self._priming = False

    def _install(self, dec, token, play):
        with self._lock:
            self._cur_token = None
        self._decoder = dec
        self._dec_token = token
        self.token = token
        self.duration = dec.duration
        if not self._ensure_stream(dec):
            self._close_decoder()
            self._seek_target = None
            self.state = STATE_STOPPED
            self._paused = True
            self._post("error", token, self.output_info.get("error", tr("Cannot open the audio device")))
            return
        for _ in range(64):                     # prefill before the device pulls
            if not self._needs_data() or not self._decode_one():
                break
        with self._lock:
            first = self._buf[0].t0 if self._buf else dec.t
        self._cb_pos = self._cb_end = first
        self._cb_perf = time.perf_counter()
        self._gain_now = 0.0
        self._fade_in = True
        self._paused = not play
        self.state = STATE_PLAYING if play else STATE_PAUSED
        self._post("loaded", token, {"duration": dec.duration, "output": dict(self.output_info), "gapless": False})
        self._post("state", token, self.state)

    def _do_seek(self, seconds):
        if self._xf is not None:
            # seeking during a crossfade: continue with whichever song is heard
            self._drop_xfade()
        heard = self._cur_token
        if heard is not None and heard != self._dec_token and heard in self._paths:
            # the decoder already moved on to the next track (gapless pre-decode)
            self.token = heard
            self._reopen(seconds, paused=self.state == STATE_PAUSED)
            return
        dec = self._decoder
        if dec is None:
            # the track is fully decoded already (seek near its end) - reopen it
            self._reopen(seconds, paused=self.state == STATE_PAUSED)
            return
        if self._held_decoder is not None:
            self._held_decoder[0].close()
            self._held_decoder = None
            self._wait_drain = False
        try:
            dec.seek(seconds)
        except Exception as exc:
            self._post("warning", self._dec_token, tr("Seek failed: {error}", error=exc))
        self._clear_buffer()
        for _ in range(16):
            if not self._needs_data() or not self._decode_one():
                break
        self._cur_token = self._dec_token
        self.token = self._dec_token
        self._cb_pos = self._cb_end = seconds
        self._cb_perf = time.perf_counter()
        self._fade_in = True
        self._seek_perf = time.perf_counter()

    def _reopen(self, position, paused):
        path = self._paths.get(self.token)
        if path is None:
            self._stop()
            return
        self._seek_target = position
        self._seek_perf = time.perf_counter()
        self._load(path, self.token, position, paused)

    def _stop(self):
        self._close_decoder()
        self._clear_buffer()
        self._next = None
        self._paused = True
        self._seek_target = None
        self._cb_pos = self._cb_end = 0.0
        self.state = STATE_STOPPED
        self._close_stream()
        self._post("state", self.token, STATE_STOPPED)

    # -- output stream ------------------------------------------------------------
    def _stream_ok(self):
        try:
            if self._stream is None or not self._stream.active:
                return False
        except Exception:
            return False
        # PortAudio can report a stream as active after the device has gone to sleep;
        # it is alive only if it has asked for audio recently (it does so even while paused)
        return not (self._last_cb_perf > 0 and time.perf_counter() - self._last_cb_perf > _STALL_SECONDS)

    def _close_stream(self):
        stream, self._stream, self._stream_key = self._stream, None, None
        self._last_cb_perf = 0.0
        if stream is not None:
            # closing a stream on a vanished device can block inside the driver: never let it hang the engine
            def close():
                for action in (stream.abort, stream.close):
                    try:
                        action()
                    except Exception:
                        pass
            closer = threading.Thread(target=close, name="T9StreamClose", daemon=True)
            closer.start()
            closer.join(1.5)
            if closer.is_alive():
                _log.warning("closing the old audio stream is hanging in the driver - left it behind")

    def _ensure_stream(self, dec):
        if sd is None:
            self.output_info = {"error": "sounddevice / PortAudio is not available"}
            return False
        device = resolve_device(self.device_name)
        dtype = np.dtype(dec.dtype).str
        if (self._stream is not None and self._stream_key[:4] == (device, dec.rate, dtype, self.exclusive)
                and self._stream_ok()):
            return True
        self._close_stream()
        latency = max(0.04, self.buffer_ms / 1000.0)
        try:
            dev_info = sd.query_devices(device) if device is not None else None
        except Exception:
            dev_info = None
        api = wasapi_index()
        is_wasapi = api is not None and dev_info is not None and dev_info["hostapi"] == api
        default_rate = int(dev_info["default_samplerate"]) if dev_info else 48000
        attempts = []
        if is_wasapi and self.exclusive:
            attempts.append(("WASAPI Exclusive", dec.rate, dict(exclusive=True, explicit_sample_format=True)))
            attempts.append(("WASAPI Exclusive", dec.rate, dict(exclusive=True)))
        if is_wasapi:
            attempts.append(("WASAPI Shared", dec.rate, dict(auto_convert=True)))
            attempts.append(("WASAPI Shared (resampled)", default_rate, {}))
        else:
            attempts.append(("Default output", dec.rate, None))
            attempts.append(("Default output (resampled)", default_rate, None))
        last_error = ""
        for label, rate, extra in attempts:
            try:
                stream = sd.OutputStream(
                    samplerate=rate, device=device, channels=2, dtype=dtype,
                    latency=latency, callback=self._callback,
                    extra_settings=sd.WasapiSettings(**extra) if extra is not None else None,
                    dither_off=True, clip_off=True,
                )
            except Exception as exc:
                last_error = str(exc)
                continue
            resampled = rate != dec.rate
            if resampled:
                dec.set_target_rate(rate)
            exclusive = bool(extra and extra.get("exclusive"))
            self._stream = stream
            self._stream_key = (device, rate, dtype, self.exclusive, resampled)
            self.output_info = {
                "mode": label,
                "device": dev_info["name"] if dev_info else "Default",
                "rate": rate,
                "src_rate": dec.src_rate,
                "bits": dec.bits,
                "float": dec.is_float,
                "exclusive": exclusive,
                "explicit_format": bool(extra and extra.get("explicit_sample_format")),
                "resampled": resampled,
                "native": dec.native and not resampled and dec._int_scale is None,
                "crossfade": self.crossfade,
                "latency": float(stream.latency),
            }
            try:
                stream.start()
            except Exception as exc:
                last_error = str(exc)
                self._close_stream()
                continue
            self._last_cb_perf = time.perf_counter()     # a stream that never calls back counts as stalled
            _log.info("output: %s on %r, %d Hz %s, latency %.0f ms", label, self.output_info["device"], rate,
                      dtype, float(stream.latency) * 1000)
            if self.exclusive and not exclusive:
                self._post("warning", None, tr("Exclusive mode is not available on this device right now ({reason}) - playing in shared mode", reason=last_error or tr("in use by another app")))
            return True
        self.output_info = {"error": tr("Cannot open the audio device") + f": {last_error}"}
        _log.error("cannot open the audio device %r: %s", device, last_error)
        return False


def is_bit_perfect(info, volume, muted):
    """True only when the device accepted our exact sample format at the file's own rate."""
    return bool(
        info and info.get("exclusive") and info.get("explicit_format") and info.get("native")
        and not info.get("float") and not muted and volume >= 0.999
    )


def describe_output(info, volume=1.0, muted=False):
    if not info:
        return ""
    if info.get("error"):
        return info["error"]
    khz = "%g" % round(info.get("rate", 0) / 1000.0, 1)
    parts = [info.get("mode", ""), f"{khz} kHz"]
    if info.get("bits") and not info.get("float"):
        parts.append(f"{info['bits']}-bit")
    elif info.get("float"):
        parts.append("32-bit float")
    if is_bit_perfect(info, volume, muted):
        parts.append(tr("Bit-perfect"))
    elif info.get("exclusive") and info.get("explicit_format") and info.get("native") and not info.get("float"):
        parts.append(tr("bit-perfect at 100% volume"))
    elif info.get("exclusive") and info.get("native"):
        parts.append(tr("native sample rate (the driver converts the sample format)"))
    if info.get("resampled"):
        parts.append(tr("resampled from {khz} kHz", khz="%g" % round(info.get("src_rate", 0) / 1000.0, 1)))
    if info.get("crossfade"):
        parts.append(tr("crossfade {n} s", n=info["crossfade"]))
    return " · ".join(p for p in parts if p)
