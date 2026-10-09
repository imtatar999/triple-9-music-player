"""Application entry point: logging, crash safety, single instance, startup."""

import faulthandler
import logging
import os
import sys
import threading
import traceback

from . import APP_NAME, APP_VERSION, paths

_log = logging.getLogger("t9player")


def _setup_logging():
    paths.ensure_dirs()
    log_file = os.path.join(paths.LOG_DIR, "t9player.log")
    try:
        if os.path.isfile(log_file) and os.path.getsize(log_file) > 2_000_000:
            os.replace(log_file, log_file + ".old")
    except OSError:
        pass
    logging.basicConfig(
        filename=log_file, level=logging.INFO, encoding="utf-8",
        format="%(asctime)s %(levelname)s %(threadName)s: %(message)s")
    try:
        # native crashes (driver bugs etc.) still leave a trace
        fh = open(os.path.join(paths.LOG_DIR, "native_crash.log"), "a", encoding="utf-8")
        faulthandler.enable(fh)
    except Exception:
        pass

    def excepthook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        _log.error("Unhandled error:\n%s", "".join(traceback.format_exception(exc_type, exc, tb)))

    def thread_hook(args):
        _log.error("Unhandled error in thread %s:\n%s", args.thread.name if args.thread else "?",
                   "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))

    # errors are logged, the program keeps running
    sys.excepthook = excepthook
    threading.excepthook = thread_hook


def _audio_args(argv):
    from . import meta
    out = []
    for arg in argv:
        if arg.startswith("-"):
            continue
        if os.path.isdir(arg) or (os.path.isfile(arg) and (meta.is_audio(arg) or arg.lower().endswith((".m3u", ".m3u8")))):
            out.append(os.path.abspath(arg))
    return out


def _wait_for_previous():
    """After 'Restart now' the new copy waits until the old one has closed."""
    pid = os.environ.pop("T9_WAIT_PID", "")
    if not pid.isdigit() or not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        SYNCHRONIZE = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, int(pid))
        if handle:
            ctypes.windll.kernel32.WaitForSingleObject(handle, 10000)
            ctypes.windll.kernel32.CloseHandle(handle)
    except Exception:
        pass


def main(argv=None, on_ready=None):
    """on_ready(window) is called after startup - used by the UI smoke test."""
    argv = list(sys.argv[1:] if argv is None else argv)
    _setup_logging()
    _log.info("Starting %s %s", APP_NAME, APP_VERSION)
    _wait_for_previous()
    sys.setswitchinterval(0.002)     # the audio callback thread gets the GIL quickly

    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Triplenine.T9MusicPlayer")
        except Exception:
            pass

    from PySide6.QtCore import QEvent, QObject, Qt, QTimer
    from PySide6.QtGui import QFont, QIcon
    from PySide6.QtWidgets import QApplication

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication([sys.argv[0]] + argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("Triplenine")
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(QIcon(paths.ICON_FILE))

    from . import winutil
    files = _audio_args(argv)
    key = f"T9MusicPlayer-{os.environ.get('USERNAME', 'user')}"
    if os.environ.get("T9_PLAYER_DATA"):
        # a separate data folder (tests, portable copies) is a separate instance
        import hashlib
        key += "-" + hashlib.sha1(paths.DATA_DIR.encode("utf-8")).hexdigest()[:8]
    instance = winutil.SingleInstance(key)
    if instance.forward_to_running(files):
        _log.info("Another instance is running - handed over %d file(s)", len(files))
        return 0
    instance.listen()

    from . import i18n, theme
    from .settings import Settings
    settings = Settings()
    theme.load_fonts()
    i18n.set_language(settings["language"])
    if settings["theme_keys"]:
        settings.set("theme_keys", theme.open_saved(settings["theme_keys"]))
    theme.apply(settings["theme"])              # a locked or unknown theme falls back to 999
    i18n.set_language(settings["language"])

    from .covers import CoverLoader
    from .library import Library
    from .player import Player
    from .ui.main_window import MainWindow

    font = QFont(theme.FONT)
    font.setPixelSize(13)
    app.setFont(font)
    app.setStyleSheet(theme.stylesheet())

    library = Library(paths.LIBRARY_DB)
    player = Player(library, settings)
    covers = CoverLoader()
    window = MainWindow(settings, library, player, covers)
    window.setWindowIcon(QIcon(paths.ICON_FILE))

    class AppFilter(QObject):
        """Dark title bars for every window + global keyboard shortcuts."""

        def eventFilter(self, obj, event):
            try:
                etype = event.type()
                if etype == QEvent.Show and obj.isWidgetType() and obj.isWindow() and not obj.property("t9_dark"):
                    obj.setProperty("t9_dark", True)
                    winutil.dark_title_bar(obj)
                elif etype == QEvent.KeyPress and obj.isWidgetType():
                    win = obj.window()
                    if win is window or win is getattr(window, "_mini", None):
                        if window.handle_key(event):
                            return True
            except Exception:
                _log.exception("event filter")
            return False

    app_filter = AppFilter()
    app.installEventFilter(app_filter)

    def bring_up(received):
        if received:
            window.play_files(received)
        if window._mini is not None and window._mini.isVisible():
            window._mini.raise_()
            window._mini.activateWindow()
        else:
            window.show_full()
            if window.isMinimized():
                window.showNormal()

    instance.files_received.connect(bring_up)

    window.show()
    media = None
    if settings["global_media_keys"]:
        media = winutil.MediaKeys(int(window.winId()))
        app.installNativeEventFilter(media)
        media.pressed.connect(window.on_media_key)
    QTimer.singleShot(0, lambda: window.start(files))
    if on_ready is not None:
        QTimer.singleShot(50, lambda: on_ready(window))
    selftest_dir = os.environ.get("T9_SELFTEST")
    if selftest_dir:
        from . import selftest
        QTimer.singleShot(50, lambda: selftest.run(window, selftest_dir))

    code = app.exec()
    _log.info("Shutting down (exit code %s)", code)
    try:
        if media is not None:
            media.unregister()
        window.shutdown()
        library.cancel_scan()
        player.shutdown()
        covers.shutdown()
        library.close()
    except Exception:
        _log.exception("shutdown")
    return code


if __name__ == "__main__":
    sys.exit(main())
