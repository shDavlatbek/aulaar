"""Main window: device card and navigation on the left, HUB-style settings pages on the right."""

from __future__ import annotations

import os
import time

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..manager import DeviceManager, DeviceState
from ..protocol import evision
from . import draft
from .dpi import DpiPage
from .parameters import ParametersPage
from .performance import PerformancePage
from .version import VersionPage
from .widgets import BatteryBadge, MouseHero

APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class MessagePage(QWidget):
    retry = Signal()

    def __init__(self):
        super().__init__(objectName="PageBody")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 48, 48, 48)
        layout.addStretch(1)
        self.title = QLabel(objectName="EmptyTitle", alignment=Qt.AlignCenter)
        self.text = QLabel(objectName="EmptyText", alignment=Qt.AlignCenter, wordWrap=True)
        self.code = QLabel(objectName="Code", alignment=Qt.AlignCenter)
        self.code.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.button = QPushButton("Try again", objectName="Primary")
        self.button.clicked.connect(self.retry)
        for w in (self.title, self.text):
            layout.addWidget(w)
        layout.addSpacing(12)
        layout.addWidget(self.code, 0, Qt.AlignCenter)
        layout.addSpacing(8)
        layout.addWidget(self.button, 0, Qt.AlignCenter)
        layout.addStretch(2)

    def show_message(self, title: str, text: str, code: str = "", button: bool = True) -> None:
        self.title.setText(title)
        self.text.setText(text)
        self.code.setText(code)
        self.code.setVisible(bool(code))
        self.button.setVisible(button)


class MainWindow(QMainWindow):
    trayChanged = Signal()

    def __init__(self, manager: DeviceManager):
        super().__init__()
        self.manager = manager
        self.current: str | None = None
        self.pending: draft.Changes = {}  # staged edits for the current device
        self._applying = ""  # "" idle, "requested" sent to the worker, "running" worker busy with it
        self.keep_in_tray = True
        self._last_refresh = 0.0
        self.setWindowTitle("Aulaar")
        self.resize(1120, 780)
        self.setMinimumSize(920, 620)

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_sidebar())
        root.addWidget(self._build_content(), 1)
        self.setCentralWidget(central)

        manager.changed.connect(self._on_changed)
        manager.error.connect(self._on_error)
        QShortcut(QKeySequence.Save, self, activated=self.apply_pending)
        self._update_all()

    # -- layout ----------------------------------------------------------------------------------

    def _build_sidebar(self) -> QWidget:
        side = QWidget(objectName="Sidebar")
        side.setFixedWidth(270)
        v = QVBoxLayout(side)
        v.setContentsMargins(18, 22, 18, 14)
        v.setSpacing(6)
        self.hero = MouseHero()
        v.addWidget(self.hero)
        self.device_name = QLabel("No mouse", objectName="DeviceName", alignment=Qt.AlignCenter, wordWrap=True)
        v.addWidget(self.device_name)
        self.device_meta = QLabel("", objectName="DeviceMeta", alignment=Qt.AlignCenter, wordWrap=True)
        v.addWidget(self.device_meta)
        row = QHBoxLayout()
        row.addStretch(1)
        self.battery = BatteryBadge()
        row.addWidget(self.battery)
        row.addStretch(1)
        v.addLayout(row)
        v.addSpacing(8)
        self.picker = QComboBox()
        self.picker.currentIndexChanged.connect(self._picked)
        v.addWidget(self.picker)
        v.addSpacing(10)

        self.nav = QButtonGroup(self)
        self.nav_buttons = []
        for i, name in enumerate(("DPI Settings", "Performance Settings", "Parameter Settings", "Version Settings")):
            b = QPushButton(name, objectName="NavButton", checkable=True)
            b.setCursor(Qt.PointingHandCursor)
            self.nav.addButton(b, i)
            self.nav_buttons.append(b)
            v.addWidget(b)
        self.nav_buttons[0].setChecked(True)
        self.nav.idClicked.connect(self._navigate)
        v.addStretch(1)
        v.addWidget(QLabel(f"Aulaar {__version__} · unofficial, not affiliated with AULA", objectName="Footer", wordWrap=True))
        return side

    def _build_content(self) -> QWidget:
        content = QWidget(objectName="Content")
        v = QVBoxLayout(content)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        top = QHBoxLayout()
        top.setContentsMargins(32, 12, 32, 0)
        self.banner = QLabel(objectName="Banner", wordWrap=True)
        self.banner.setProperty("kind", "error")
        self.banner.hide()
        top.addWidget(self.banner, 1)
        self.busy = QLabel("", objectName="BusyLabel")
        top.addWidget(self.busy, 0, Qt.AlignRight | Qt.AlignVCenter)
        v.addLayout(top)
        self._banner_timer = QTimer(self, singleShot=True, interval=8000)
        self._banner_timer.timeout.connect(self.banner.hide)

        self.stack = QStackedWidget()
        self.message = MessagePage()
        self.message.retry.connect(self._retry)
        self.pages = [DpiPage(self.manager), PerformancePage(self.manager), ParametersPage(self.manager), VersionPage(self.manager)]
        self.pages_stack = QStackedWidget()
        for p in self.pages:
            p.on_edit = self._edit
            self.pages_stack.addWidget(p)
        self.stack.addWidget(self.message)
        self.stack.addWidget(self.pages_stack)
        v.addWidget(self.stack, 1)
        v.addWidget(self._build_apply_bar())
        return content

    def _build_apply_bar(self) -> QWidget:
        self.apply_bar = QFrame(objectName="ApplyBar")
        h = QHBoxLayout(self.apply_bar)
        h.setContentsMargins(32, 12, 32, 12)
        h.setSpacing(10)
        dot = QLabel("●", objectName="ApplyDot")
        h.addWidget(dot)
        self.apply_text = QLabel(objectName="ApplyText", wordWrap=True)
        h.addWidget(self.apply_text, 1)
        self.discard_btn = QPushButton("Discard")
        self.discard_btn.setCursor(Qt.PointingHandCursor)
        self.discard_btn.clicked.connect(self.discard_pending)
        h.addWidget(self.discard_btn)
        self.apply_btn = QPushButton("Apply", objectName="Primary")
        self.apply_btn.setCursor(Qt.PointingHandCursor)
        self.apply_btn.setToolTip("Write the changes to the mouse (Ctrl+S)")
        self.apply_btn.clicked.connect(self.apply_pending)
        h.addWidget(self.apply_btn)
        self.apply_bar.hide()
        return self.apply_bar

    # -- state -----------------------------------------------------------------------------------

    def state(self) -> DeviceState | None:
        return self.manager.states.get(self.current) if self.current else None

    def _on_changed(self, key: str) -> None:
        if key == "" or self.current not in self.manager.states:
            self._update_all()
        elif key == self.current:
            self._update_current()
        self.trayChanged.emit()

    def _update_all(self) -> None:
        states = sorted(self.manager.states.values(), key=lambda s: (s.link, s.key))
        if self.current not in self.manager.states:
            preferred = self.manager.preferred()
            self.current = preferred.key if preferred else None
            self.pending = {}
            self._applying = ""
        self.picker.blockSignals(True)
        self.picker.clear()
        for s in states:
            self.picker.addItem(f"{s.name} · {s.link_name}", s.key)
        if self.current:
            self.picker.setCurrentIndex(self.picker.findData(self.current))
        self.picker.blockSignals(False)
        self.picker.setVisible(len(states) > 1)
        self._update_current()

    def _picked(self, index: int) -> None:
        key = self.picker.itemData(index)
        if key and key != self.current:
            if not self._confirm_discard("switching devices"):
                self.picker.blockSignals(True)
                self.picker.setCurrentIndex(self.picker.findData(self.current))
                self.picker.blockSignals(False)
                return
            self.current = key
            self.pending = {}
            self._applying = ""
            self._update_current()
            self.trayChanged.emit()

    def _update_current(self) -> None:
        st = self.state()
        for b in self.nav_buttons:
            b.setEnabled(bool(st and st.settings is not None and st.online))
        if st is None:
            self.hero.set(None, None, True)
            self.device_name.setText("No AULA mouse")
            self.device_meta.setText("")
            self.battery.setLevel(None, "—")
            self.busy.setText("")
            self.message.show_message(
                "No AULA mouse found",
                "Connect your mouse with its USB cable, or plug in the AULA 8K Dongle.\n"
                "Supported: V9, V9+, V9 Pro/Pro+, V9 Ultra/Ultra+, V9 Max/Max+, X9 series.",
            )
            self.stack.setCurrentWidget(self.message)
            self.pending = {}
            self._applying = ""
            self._update_apply_bar(None)
            return

        self.device_name.setText(st.name)
        if st.busy:
            self.busy.setText("Syncing with mouse…")
        elif self.busy.text() == "Syncing with mouse…":
            self.busy.setText("")
        s = st.settings
        glow = None
        if s is not None and 0 <= s.active_stage < len(s.stages):
            glow = s.stages[s.active_stage].color
        preview = draft.apply_changes(s, self.pending) if s is not None else None
        if preview is not None and 0 <= preview.active_stage < len(preview.stages):
            glow = preview.stages[preview.active_stage].color
        self.hero.set(st.battery, glow, not st.online)
        meta = [st.link_name]
        if st.link_name == "2.4G":
            meta.append(st.product_name)
        if s is not None and 0 <= s.active_stage < len(s.stages):
            stage = s.stages[s.active_stage]
            meta.append(f"{stage.x} DPI")
        self.device_meta.setText(" · ".join(meta))
        if st.online:
            self.battery.setLevel(st.battery, None if st.battery is not None else "—")
        else:
            self.battery.setLevel(None, "asleep" if st.status else "—")

        if st.no_permission:
            self.message.show_message(
                "Permission needed",
                "Aulaar can't open the mouse yet. Run the installer once (it asks for your password), "
                "then press Try again.",
                f"cd {APP_DIR} && ./install.sh",
            )
            self.stack.setCurrentWidget(self.message)
        elif st.status is None:
            if st.error:
                self.message.show_message("Couldn't read the mouse", st.error)
            else:
                self.message.show_message("Connecting…", "Reading settings from the mouse.", button=False)
            self.stack.setCurrentWidget(self.message)
        elif not st.online:
            self.message.show_message(
                "Mouse is asleep",
                f"The {st.product_name} is connected, but the mouse isn't answering.\n"
                "Move or click the mouse to wake it up — Aulaar checks again every few seconds.",
                button=True,
            )
            self.stack.setCurrentWidget(self.message)
        elif s is None:
            self.message.show_message("Couldn't read the settings", st.error or "Try again in a moment.")
            self.stack.setCurrentWidget(self.message)
        else:
            self.pending = draft.prune(s, self.pending)
            self._render_pages(st)
            self.stack.setCurrentWidget(self.pages_stack)
        self._update_apply_bar(st)

    # -- pending changes -------------------------------------------------------------------------

    def _render_pages(self, st: DeviceState) -> None:
        preview = draft.apply_changes(st.settings, self.pending) if st.settings is not None else None
        for p in self.pages:
            p.set_state(st, preview)

    def _edit(self, fn) -> None:
        """A page changed something: stage it on top of what the mouse reports."""
        st = self.state()
        if st is None or st.settings is None:
            return
        edited = draft.apply_changes(st.settings, self.pending)
        fn(edited)
        self.pending = draft.diff(st.settings, edited)
        self._render_pages(st)
        self._update_apply_bar(st)
        self._update_hero_preview(st)

    def _update_hero_preview(self, st: DeviceState) -> None:
        preview = draft.apply_changes(st.settings, self.pending)
        glow = preview.stages[preview.active_stage].color if 0 <= preview.active_stage < len(preview.stages) else None
        self.hero.set(st.battery, glow, not st.online)

    def _update_apply_bar(self, st: DeviceState | None) -> None:
        if st is not None and self._applying:
            if st.busy:
                self._applying = "running"
            elif self._applying == "running":
                self._applying = ""
                if not self.pending and st.error is None:
                    self._flash("Saved to the mouse ✓")
        has = bool(self.pending) and st is not None and st.online and st.settings is not None
        self.apply_bar.setVisible(has)
        if not has:
            return
        names = draft.labels(self.pending)
        count = len(names)  # per setting, not per byte (e.g. Wave also flips the "colorful" flag)
        self.apply_text.setText(
            f"{count} unsaved change{'s' if count != 1 else ''}: {', '.join(names)}"
        )
        busy = st.busy or bool(self._applying)
        self.apply_btn.setEnabled(not busy)
        self.discard_btn.setEnabled(not busy)
        self.apply_btn.setText("Applying…" if busy else "Apply")

    def apply_pending(self) -> None:
        st = self.state()
        if not self.pending or st is None or st.settings is None or not st.online or st.busy:
            return
        changes = dict(self.pending)
        problems = evision.validate(draft.apply_changes(st.settings, changes))
        known = set(evision.validate(st.settings))
        if bad := [p for p in problems if p not in known]:
            self._on_error(st.key, "Can't apply: " + ", ".join(bad))
            return
        self._applying = "requested"
        count = len(changes)
        self.manager.apply(
            st.key,
            lambda s: draft.apply_changes(s, changes),
            f"Saving {count} change{'s' if count != 1 else ''}",
        )
        self.apply_btn.setEnabled(False)
        self.discard_btn.setEnabled(False)
        self.apply_btn.setText("Applying…")

    def discard_pending(self) -> None:
        st = self.state()
        self.pending = {}
        if st is not None and st.settings is not None:
            self._render_pages(st)
            self._update_hero_preview(st)
        self._update_apply_bar(st)

    def _confirm_discard(self, action: str) -> bool:
        if not self.pending:
            return True
        answer = QMessageBox.question(
            self,
            "Unsaved changes",
            f"You have unsaved changes. Discard them before {action}?",
            QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        return answer == QMessageBox.Discard

    def factory_reset(self, key: str) -> None:
        self.pending = {}
        self.manager.factory_reset(key)

    def _flash(self, text: str) -> None:
        self.busy.setText(text)
        QTimer.singleShot(3000, lambda: self.busy.text() == text and self.busy.setText(""))

    def _navigate(self, index: int) -> None:
        self.pages_stack.setCurrentIndex(index)

    def _retry(self) -> None:
        if self.current:
            self.manager.refresh(self.current, True)
        self.manager.rescan()

    def _on_error(self, key: str, message: str) -> None:
        if key != self.current:
            return
        self.banner.setText(message)
        self.banner.show()
        self._banner_timer.start()

    # -- window behavior ---------------------------------------------------------------------------

    def show_and_raise(self) -> None:
        self.show()
        self.setWindowState((self.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
        self.raise_()
        self.activateWindow()

    def toggle(self) -> None:
        if self.isVisible() and self.isActiveWindow():
            self.hide()
        else:
            self.show_and_raise()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        # The DPI button on the mouse changes the active stage without telling us; re-read on focus.
        if event.type() == QEvent.ActivationChange and self.isActiveWindow() and self.current:
            if time.monotonic() - self._last_refresh > 5:
                self._last_refresh = time.monotonic()
                self.manager.refresh(self.current, True)

    def closeEvent(self, event) -> None:
        if self.keep_in_tray:
            event.ignore()
            self.hide()
        else:
            event.accept()
