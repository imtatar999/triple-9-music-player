"""Diagnostics: a readable activity log and a watchdog that notices freezes.

Everything goes to %APPDATA%\\T9 Music Player\\logs\\t9player.log (rotated, a few MB at most).
The watchdog runs in its own thread and writes down where the program was stuck when the
window stopped responding or the audio engine hung - the kind of thing that is impossible to
see afterwards otherwise. Nothing is ever sent anywhere.
"""

import logging
import sys
import threading
import time
import traceback

_log = logging.getLogger("t9player.watchdog")


def thread_stack(thread_id):
    frame = sys._current_frames().get(thread_id)
    if frame is None:
        return "(no stack)"
    return "".join(traceback.format_stack(frame, limit=25))


class Watchdog:
    """Logs when the UI thread or the audio engine thread stops ticking for a few seconds."""

    def __init__(self, ui_thread_id, engine=None, limit=3.0):
        self.ui_thread_id = ui_thread_id
        self.engine = engine
        self.limit = limit
        self.ui_beat = time.perf_counter()
        self._ui_frozen_since = None
        self._engine_frozen_since = None
        self._thread = threading.Thread(target=self._run, name="T9Watchdog", daemon=True)
        self._thread.start()

    def beat(self):
        """Called from a Qt timer in the UI thread."""
        now = time.perf_counter()
        if self._ui_frozen_since is not None:
            _log.warning("UI responsive again after %.1f s", now - self._ui_frozen_since)
            self._ui_frozen_since = None
        self.ui_beat = now

    def _run(self):
        while True:
            time.sleep(1.0)
            now = time.perf_counter()
            if self._ui_frozen_since is None and now - self.ui_beat > self.limit:
                self._ui_frozen_since = self.ui_beat
                _log.warning("UI not responding for %.1f s - it was here:\n%s",
                             now - self.ui_beat, thread_stack(self.ui_thread_id))
            engine = self.engine
            if engine is None or not engine.alive:
                continue
            gap = now - engine.heartbeat
            if gap > self.limit and self._engine_frozen_since is None:
                self._engine_frozen_since = engine.heartbeat
                _log.warning("Audio engine stuck for %.1f s - it was here:\n%s",
                             gap, thread_stack(engine.thread_id))
            elif gap <= self.limit and self._engine_frozen_since is not None:
                _log.warning("Audio engine running again after %.1f s", now - self._engine_frozen_since)
                self._engine_frozen_since = None
