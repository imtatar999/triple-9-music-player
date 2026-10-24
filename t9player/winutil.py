"""Windows integration: dark title bars, global media keys, single instance."""

import ctypes
import sys

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

IS_WIN = sys.platform.startswith("win")

WM_HOTKEY = 0x0312
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_STOP = 0xB2
VK_MEDIA_PLAY_PAUSE = 0xB3
_HOTKEYS = {
    0x7901: ("play_pause", VK_MEDIA_PLAY_PAUSE),
    0x7902: ("next", VK_MEDIA_NEXT_TRACK),
    0x7903: ("previous", VK_MEDIA_PREV_TRACK),
    0x7904: ("stop", VK_MEDIA_STOP),
}


def dark_title_bar(widget):
    """Ask DWM for a dark window frame (Windows 10 1809+ / 11). Harmless elsewhere."""
    if not IS_WIN:
        return
    try:
        hwnd = int(widget.winId())
        value = ctypes.c_int(1)
        for attr in (20, 19):   # DWMWA_USE_IMMERSIVE_DARK_MODE (new / old builds)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
        # Windows 11: caption colour close to the app background
        color = ctypes.c_int(0x000B0A09)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(color), ctypes.sizeof(color))
    except Exception:
        pass


class _MSG(ctypes.Structure):
    _fields_ = [("hwnd", ctypes.c_void_p), ("message", ctypes.c_uint), ("wParam", ctypes.c_size_t),
                ("lParam", ctypes.c_ssize_t), ("time", ctypes.c_uint), ("pt_x", ctypes.c_long),
                ("pt_y", ctypes.c_long)]


class MediaKeys(QObject, QAbstractNativeEventFilter):
    """Registers the keyboard media keys as global hotkeys (when no other app owns them)."""
    pressed = Signal(str)

    def __init__(self, hwnd, parent=None):
        QObject.__init__(self, parent)
        QAbstractNativeEventFilter.__init__(self)
        self.hwnd = hwnd
        self.registered = []
        if not IS_WIN:
            return
        user32 = ctypes.windll.user32
        for hk_id, (_, vk) in _HOTKEYS.items():
            try:
                if user32.RegisterHotKey(ctypes.c_void_p(hwnd), hk_id, 0x4000, vk):   # MOD_NOREPEAT
                    self.registered.append(hk_id)
            except Exception:
                pass

    def nativeEventFilter(self, event_type, message):
        try:
            if event_type in (b"windows_generic_MSG", "windows_generic_MSG"):
                msg = _MSG.from_address(int(message))
                if msg.message == WM_HOTKEY and msg.wParam in _HOTKEYS:
                    self.pressed.emit(_HOTKEYS[msg.wParam][0])
                    return True, 0
        except Exception:
            pass
        return False, 0

    def unregister(self):
        if not IS_WIN:
            return
        for hk_id in self.registered:
            try:
                ctypes.windll.user32.UnregisterHotKey(ctypes.c_void_p(self.hwnd), hk_id)
            except Exception:
                pass
        self.registered = []


class SingleInstance(QObject):
    """First instance listens on a local socket; later ones forward their files and exit."""
    files_received = Signal(list)

    def __init__(self, key, parent=None):
        super().__init__(parent)
        self.key = key
        self.server = None

    def forward_to_running(self, files):
        sock = QLocalSocket()
        sock.connectToServer(self.key)
        if not sock.waitForConnected(400):
            return False
        payload = ("\n".join(files) if files else "__show__").encode("utf-8")
        sock.write(payload)
        sock.flush()
        sock.waitForBytesWritten(800)
        sock.disconnectFromServer()
        return True

    def listen(self):
        self.server = QLocalServer(self)
        if not self.server.listen(self.key):
            QLocalServer.removeServer(self.key)
            self.server.listen(self.key)
        self.server.newConnection.connect(self._on_connection)

    def _on_connection(self):
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            sock.readyRead.connect(lambda s=sock: self._read(s))
            sock.disconnected.connect(sock.deleteLater)

    def _read(self, sock):
        try:
            data = bytes(sock.readAll()).decode("utf-8", errors="replace")
        except Exception:
            return
        files = [] if data.strip() == "__show__" else [ln for ln in data.split("\n") if ln.strip()]
        self.files_received.emit(files)
