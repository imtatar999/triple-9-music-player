"""Playback controller: queue, shuffle, repeat, history, gapless hand-off.

Lives in the Qt thread, talks to the AudioEngine only through commands and
the engine's event queue (polled by a timer), so nothing here can block.
"""

import itertools
import logging
import random
import time

from PySide6.QtCore import QObject, QTimer, Signal

from . import audio
from .i18n import tr

_log = logging.getLogger("t9player.player")


class Player(QObject):
    track_changed = Signal(object)          # Track or None
    state_changed = Signal(str)
    queue_changed = Signal()
    modes_changed = Signal()                # shuffle / repeat
    volume_changed = Signal(float, bool)
    output_changed = Signal(dict)
    duration_changed = Signal(float)
    message = Signal(str, str)              # level, text
    favorite_changed = Signal(object)
    play_counted = Signal(object)

    def __init__(self, library, settings, parent=None):
        super().__init__(parent)
        self.library = library
        self.settings = settings
        self.engine = audio.AudioEngine()
        self.engine.volume = settings["volume"]
        self.engine.muted = settings["muted"]
        self.engine.exclusive = settings["exclusive_mode"]
        self.engine.device_name = settings["output_device"]
        self.engine.buffer_ms = settings["buffer_ms"]
        self.engine.gapless = settings["gapless"]
        self.engine.crossfade = settings["crossfade"]
        self.queue = []                     # list[Track]
        self.index = -1
        self.order = []                     # play order (indices into queue)
        self.shuffle = settings["shuffle"]
        self.repeat = settings["repeat"]
        self.state = audio.STATE_STOPPED
        self.current = None
        self.duration = 0.0
        self.output_info = {}
        self._tokens = itertools.count(1)
        self._token_map = {}                # token -> queue index
        self._token = None                  # token we expect to hear
        self._failures = 0
        self._counted = False
        self._stop_after_current = False
        self.sleep_deadline = 0.0           # perf time when playback stops (0 = off)
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

    # ------------------------------------------------------------------ queue
    def play_tracks(self, tracks, start=0, position=0.0, paused=False):
        tracks = [t for t in tracks if t is not None]
        if not tracks:
            return
        self.queue = list(tracks)
        start = max(0, min(start, len(self.queue) - 1))
        self._rebuild_order(start)
        self._failures = 0
        self._play_index(start, position, paused)
        self.queue_changed.emit()

    def enqueue(self, tracks, play_next=False):
        tracks = [t for t in tracks if t is not None]
        if not tracks:
            return
        if not self.queue or self.index < 0:
            self.play_tracks(tracks)
            return
        if play_next:
            insert_at = self.index + 1
            self.queue[insert_at:insert_at] = tracks
            new = list(range(insert_at, insert_at + len(tracks)))
            self.order = [i + len(tracks) if i >= insert_at else i for i in self.order]
            pos = self.order.index(self.index) + 1 if self.index in self.order else len(self.order)
            self.order[pos:pos] = new
        else:
            base = len(self.queue)
            self.queue.extend(tracks)
            new = list(range(base, base + len(tracks)))
            if self.shuffle:
                pos = self.order.index(self.index) + 1 if self.index in self.order else 0
                rest = self.order[pos:] + new
                random.shuffle(rest)
                self.order = self.order[:pos] + rest
            else:
                self.order.extend(new)
        self._sync_tokens()
        self._send_next()
        self.queue_changed.emit()

    def remove_from_queue(self, qindex):
        if not 0 <= qindex < len(self.queue) or qindex == self.index:
            return
        del self.queue[qindex]
        self.order = [i - 1 if i > qindex else i for i in self.order if i != qindex]
        if self.index > qindex:
            self.index -= 1
        self._sync_tokens()
        self._send_next()
        self.queue_changed.emit()

    def clear_upcoming(self):
        if self.index < 0:
            return
        cur = self.queue[self.index]
        self.queue = [cur]
        self.index = 0
        self.order = [0]
        self._sync_tokens()
        self._send_next()
        self.queue_changed.emit()

    def upcoming(self):
        """[(queue_index, Track)] in play order after the current track."""
        if self.index not in self.order:
            return []
        pos = self.order.index(self.index)
        return [(i, self.queue[i]) for i in self.order[pos + 1:]]

    def _rebuild_order(self, first):
        n = len(self.queue)
        if self.shuffle:
            rest = [i for i in range(n) if i != first]
            random.shuffle(rest)
            self.order = [first] + rest
        else:
            self.order = list(range(n))

    def _sync_tokens(self):
        """Queue edits shift indices: keep the token of the current track valid."""
        if self._token is not None and 0 <= self.index < len(self.queue):
            self._token_map = {self._token: self.index}

    # ------------------------------------------------------------------ transport
    def _play_index(self, qindex, position=0.0, paused=False):
        if not 0 <= qindex < len(self.queue):
            return
        track = self.queue[qindex]
        token = next(self._tokens)
        self._token_map = {token: qindex}
        self._token = token
        self.index = qindex
        self._set_current(track)
        self._counted = False
        _log.info("play %r - %r (%s, queue %d/%d)%s", track.display_artist, track.title, track.format_label,
                  qindex + 1, len(self.queue), f" from {position:.0f} s" if position else "")
        self.engine.load(track.path, token, position, paused)
        self._send_next()

    def _set_current(self, track):
        self.current = track
        self.duration = track.duration if track else 0.0
        self.track_changed.emit(track)
        self.duration_changed.emit(self.duration)

    def _next_index(self, auto):
        if not self.queue:
            return None
        if auto and self.repeat == "one":
            return self.index
        if self.index not in self.order:
            return self.order[0] if self.order else None
        pos = self.order.index(self.index)
        if pos + 1 < len(self.order):
            return self.order[pos + 1]
        if self.repeat in ("all", "one"):
            return self.order[0]
        return None

    def _prev_index(self):
        if self.index not in self.order:
            return None
        pos = self.order.index(self.index)
        if pos > 0:
            return self.order[pos - 1]
        if self.repeat == "all":
            return self.order[-1]
        return None

    def _send_next(self):
        """Tell the engine what follows, so it can pre-decode it (gapless)."""
        if self._stop_after_current:
            self.engine.set_next(None, None)
            return
        nxt = self._next_index(auto=True) if self.repeat == "one" else self._peek_next()
        if nxt is None:
            self.engine.set_next(None, None)
            return
        token = next(self._tokens)
        self._token_map[token] = nxt
        self.engine.set_next(self.queue[nxt].path, token)

    def _peek_next(self):
        if self.index not in self.order:
            return None
        pos = self.order.index(self.index)
        if pos + 1 < len(self.order):
            return self.order[pos + 1]
        if self.repeat == "all" and self.order:
            return self.order[0]
        return None

    def play_pause(self):
        if self.current is None:
            if self.queue:
                self._play_index(max(0, self.index))
            return
        if self.state == audio.STATE_PLAYING:
            self.engine.pause()
        elif self.state == audio.STATE_PAUSED:
            self.engine.resume()
        else:
            self._play_index(self.index, 0.0)

    def play(self):
        if self.state != audio.STATE_PLAYING:
            self.play_pause()

    def pause(self):
        if self.state == audio.STATE_PLAYING:
            self.engine.pause()

    def stop(self):
        self.engine.stop()

    def next(self):
        nxt = self._next_index(auto=False)
        if nxt is None:
            if self.queue and self.repeat == "off":
                self.message.emit("info", tr("End of the queue"))
            return
        self._play_index(nxt, paused=False)

    def previous(self):
        if self.position() > 3.0 or self._prev_index() is None:
            self.seek(0.0)
            if self.state == audio.STATE_STOPPED and self.current is not None:
                self._play_index(self.index)
            return
        self._play_index(self._prev_index())

    def jump_to(self, qindex):
        if 0 <= qindex < len(self.queue):
            if self.shuffle and qindex in self.order:
                # keep the shuffled order, just continue from the chosen track
                pass
            self._play_index(qindex)

    def seek(self, seconds):
        if self.current is None:
            return
        seconds = max(0.0, min(seconds, max(0.0, self.duration - 0.25) if self.duration else seconds))
        if self.state == audio.STATE_STOPPED:
            self._play_index(self.index, seconds, paused=False)
        else:
            self.engine.seek(seconds)

    def seek_relative(self, delta):
        self.seek(self.position() + delta)

    def position(self):
        return self.engine.position() if self.current is not None else 0.0

    # ------------------------------------------------------------------ modes
    def set_shuffle(self, value):
        self.shuffle = bool(value)
        if self.queue and self.index >= 0:
            self._rebuild_order(self.index)
        self.settings.set("shuffle", self.shuffle)
        self._send_next()
        self.modes_changed.emit()
        self.queue_changed.emit()

    def cycle_repeat(self):
        self.repeat = {"off": "all", "all": "one", "one": "off"}[self.repeat]
        self.settings.set("repeat", self.repeat)
        self._send_next()
        self.modes_changed.emit()

    def set_volume(self, volume, save=True):
        volume = min(1.0, max(0.0, float(volume)))
        self.engine.volume = volume
        if volume > 0 and self.engine.muted:
            self.engine.muted = False
        if save:
            self.settings.set("volume", volume, save=False)
            self.settings.set("muted", self.engine.muted, save=False)
        self.volume_changed.emit(volume, self.engine.muted)

    def save_volume(self):
        self.settings.set("volume", self.engine.volume, save=False)
        self.settings.set("muted", self.engine.muted)

    def toggle_mute(self):
        self.engine.muted = not self.engine.muted
        self.settings.set("muted", self.engine.muted)
        self.volume_changed.emit(self.engine.volume, self.engine.muted)

    @property
    def volume(self):
        return self.engine.volume

    @property
    def muted(self):
        return self.engine.muted

    def toggle_favorite(self, track=None):
        track = track or self.current
        if track is None:
            return
        self.library.set_favorite(track, not track.favorite)
        self.favorite_changed.emit(track)

    def set_sleep_timer(self, minutes):
        """minutes > 0: stop after that time; -1: after the current track; 0: off."""
        self._stop_after_current = minutes == -1
        self.sleep_deadline = time.perf_counter() + minutes * 60 if minutes > 0 else 0.0
        self._send_next()

    @property
    def sleep_mode(self):
        if self._stop_after_current:
            return "track"
        return "timer" if self.sleep_deadline else ""

    def apply_output_settings(self):
        s = self.settings
        self.engine.gapless = s["gapless"]
        self.engine.reconfigure(s["output_device"], s["exclusive_mode"], s["buffer_ms"], s["crossfade"])

    # ------------------------------------------------------------------ engine events
    def _poll(self):
        try:
            events = self.engine.poll_events()
        except Exception:
            return
        for kind, token, payload in events:
            try:
                self._on_event(kind, token, payload)
            except Exception as exc:     # keep the timer alive no matter what
                self.message.emit("error", tr("Internal error: {error}", error=exc))
        if self.sleep_deadline and time.perf_counter() >= self.sleep_deadline:
            self.sleep_deadline = 0.0
            self.pause()
            self.message.emit("info", tr("Sleep timer: playback paused"))
        if (not self._counted and self.current is not None and self.state == audio.STATE_PLAYING
                and self.position() > min(30.0, max(5.0, self.duration * 0.5))):
            self._counted = True
            self.library.count_play(self.current)
            self.play_counted.emit(self.current)

    def _on_event(self, kind, token, payload):
        if kind == "state":
            if token is not None and token != self._token and token not in self._token_map:
                return
            self.state = payload
            self.state_changed.emit(payload)
        elif kind == "loaded":
            if payload.get("gapless"):
                return               # becomes current only when it is heard ("started")
            if token != self._token:
                return
            self._failures = 0
            self.output_info = self._with_real_bits(payload.get("output", {}))
            self.output_changed.emit(self.output_info)
            dur = payload.get("duration") or 0.0
            if dur > 0 and (not self.duration or abs(dur - self.duration) > 1.0):
                self.duration = dur
                self.duration_changed.emit(dur)
            self._send_next()
        elif kind == "started":
            if token == self._token:
                return
            qindex = self._token_map.get(token)
            if qindex is None or not 0 <= qindex < len(self.queue):
                return
            # gapless hand-off: the next track is now audible
            self._token = token
            self._token_map = {token: qindex}
            self.index = qindex
            self._counted = False
            self._set_current(self.queue[qindex])
            self.output_info = self._with_real_bits(dict(self.engine.output_info))
            self.output_changed.emit(self.output_info)
            dur = self.engine.duration
            if dur > 0:
                self.duration = dur
                self.duration_changed.emit(dur)
            self.queue_changed.emit()
            self._send_next()
        elif kind == "eof":
            if token != self._token:
                return
            if self._stop_after_current:
                self._stop_after_current = False
                self.engine.stop()
                self.message.emit("info", tr("Stopped after the current track"))
                return
            nxt = self._next_index(auto=True)
            if nxt is None:
                self.engine.stop()
                self.state = audio.STATE_STOPPED
                self.state_changed.emit(self.state)
            else:
                self._play_index(nxt)
        elif kind == "error":
            if token is not None and token != self._token and token in self._token_map:
                # the pre-decoded next track failed; it will be retried normally
                return
            name = self.current.title if self.current else "track"
            _log.error("cannot play %r: %s", name, payload)
            self.message.emit("error", tr("Cannot play \u201c{name}\u201d: {error}", name=name, error=payload))
            if token is not None and token == self._token:
                self._failures += 1
                if self._failures < max(1, min(len(self.queue), 25)):
                    nxt = self._next_index(auto=False)
                    if nxt is not None and nxt != self.index:
                        QTimer.singleShot(150, lambda n=nxt: self._play_index(n))
                        return
                self.state = audio.STATE_STOPPED
                self.state_changed.emit(self.state)
        elif kind == "warning":
            _log.warning("engine: %s", payload)
            self.message.emit("warning", str(payload))
        elif kind == "info":
            self.message.emit("info", str(payload))

    def _with_real_bits(self, info):
        """FFmpeg reports 24-bit audio as 32-bit containers; the tags know the real depth."""
        info = dict(info)
        cur = self.current
        if cur is not None and cur.bits and info.get("bits") and not info.get("float"):
            info["bits"] = cur.bits
        return info

    def shutdown(self):
        self._timer.stop()
        self.engine.shutdown()
