"""Qt application bootstrap: single instance, theme, tray and main window."""

from __future__ import annotations

import logging
import os
import signal
import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QIcon, QPalette, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from . import APP_ID, icons
from .manager import DeviceManager
from .tray import Tray
from .ui.main_window import MainWindow

log = logging.getLogger(__name__)


def _dark_palette() -> QPalette:
    pal = QPalette()
    for role, color in {
        QPalette.Window: "#0d0f13",
        QPalette.WindowText: "#e6e9ef",
        QPalette.Base: "#161a21",
        QPalette.AlternateBase: "#1d222b",
        QPalette.Text: "#e6e9ef",
        QPalette.Button: "#1d222b",
        QPalette.ButtonText: "#e6e9ef",
        QPalette.Highlight: "#166dee",
        QPalette.HighlightedText: "#ffffff",
        QPalette.ToolTipBase: "#1d222b",
        QPalette.ToolTipText: "#e6e9ef",
        QPalette.PlaceholderText: "#8a93a6",
    }.items():
        pal.setColor(role, QColor(color))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor("#4b5263"))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#4b5263"))
    pal.setColor(QPalette.Disabled, QPalette.WindowText, QColor("#4b5263"))
    return pal


def _app_icon() -> QIcon:
    icon = QIcon()
    for size in (32, 64, 128, 256):
        icon.addPixmap(QPixmap.fromImage(icons.tray_image(size, 100)))
    return icon


def _already_running(name: str) -> bool:
    sock = QLocalSocket()
    sock.connectToServer(name)
    if sock.waitForConnected(300):
        sock.write(b"show")
        sock.flush()
        sock.waitForBytesWritten(300)
        sock.disconnectFromServer()
        return True
    return False


def run(fake_battery: int | None = None) -> int:
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Aulaar")
    app.setDesktopFileName(APP_ID)
    app.setQuitOnLastWindowClosed(False)

    server_name = f"{APP_ID}-{os.getuid()}"
    if _already_running(server_name):
        log.info("Aulaar is already running; asked it to show its window")
        return 0
    QLocalServer.removeServer(server_name)
    server = QLocalServer()
    server.listen(server_name)

    app.setStyle("Fusion")
    app.setPalette(_dark_palette())
    with open(os.path.join(os.path.dirname(__file__), "ui", "theme.qss")) as f:
        app.setStyleSheet(f.read())
    app.setWindowIcon(_app_icon())

    manager = DeviceManager(fake_battery=fake_battery)
    window = MainWindow(manager)
    tray = Tray()

    def update_tray() -> None:
        st = window.state() or manager.preferred()
        if st is None:
            tray.update(title="Aulaar", subtitle="No AULA mouse connected", level=None, asleep=True, attention=False)
            return
        if not st.online:
            sub = "Asleep — move the mouse to wake it" if st.status else "Connecting…"
            tray.update(title=st.name, subtitle=sub, level=None, asleep=True, attention=False)
            return
        level = st.battery
        sub = f"Battery {level}% · {st.link_name}" if level is not None else f"Battery unknown · {st.link_name}"
        low = level is not None and level <= icons.LOW_BATTERY
        tray.update(title=st.name, subtitle=sub + (" — charge soon" if low else ""), level=level, asleep=False, attention=low)

    window.trayChanged.connect(update_tray)
    tray.activated.connect(window.toggle)
    tray.refreshRequested.connect(lambda: manager.refresh("", True))
    tray.quitRequested.connect(app.quit)
    server.newConnection.connect(lambda: (server.nextPendingConnection(), window.show_and_raise()))
    app.aboutToQuit.connect(manager.shutdown)

    # Let Ctrl+C in a terminal quit cleanly.
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    heartbeat = QTimer(interval=500)
    heartbeat.timeout.connect(lambda: None)
    heartbeat.start()

    update_tray()
    manager.start()
    window.show()
    return app.exec()
