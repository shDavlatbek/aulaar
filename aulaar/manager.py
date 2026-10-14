"""Device discovery and I/O off the GUI thread.

`DeviceManager` lives in the GUI thread and exposes immutable `DeviceState` snapshots. All blocking
hidraw traffic happens in `_Worker` on its own QThread; requests go there through queued signals.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, replace
from typing import Callable

from PySide6.QtCore import QObject, QSocketNotifier, QThread, QTimer, Signal, Slot

from . import storage
from .device import Mouse, Status, WriteMismatch
from .devices import Found, Model, find
from .hidraw import DeviceGone
from .protocol import evision

log = logging.getLogger(__name__)

BATTERY_INTERVAL_MS = 60_000
ASLEEP_INTERVAL_MS = 10_000
EVENT_PUMP_MS = 1_500


@dataclass(frozen=True)
class DeviceState:
    key: str  # hidraw path
    product_name: str
    link: int
    status: Status | None = None
    settings: evision.Settings | None = None
    error: str | None = None
    busy: bool = False
    no_permission: bool = False

    @property
    def online(self) -> bool:
        return bool(self.status and self.status.online)

    @property
    def model(self) -> Model | None:
        return self.status.model if self.status else None

    @property
    def name(self) -> str:
        return self.model.name if self.model else self.product_name

    @property
    def link_name(self) -> str:
        return "2.4G" if self.link == evision.WIRELESS else "Wired"

    @property
    def battery(self) -> int | None:
        return self.status.battery if self.status and self.status.online else None


class _Worker(QObject):
    stateChanged = Signal(object)  # DeviceState
    removed = Signal(str)
    failed = Signal(str, str)  # key, message for the user

    def __init__(self, fake_battery: int | None):
        super().__init__()
        self.fake_battery = fake_battery
        self.mice: dict[str, Mouse] = {}
        self.states: dict[str, DeviceState] = {}
        self._pending_events: set[str] = set()

    # -- helpers ---------------------------------------------------------------------------------

    def _publish(self, key: str, **changes) -> None:
        state = replace(self.states[key], **changes)
        self.states[key] = state
        self.stateChanged.emit(state)

    def _on_event(self, key: str) -> Callable[[str, bytes], None]:
        def handler(name: str, data: bytes) -> None:
            log.info("%s: device event %s", key, name)
            self._pending_events.add(key)

        return handler

    def _run(self, key: str, what: str, fn: Callable[[Mouse], None]) -> None:
        mouse = self.mice.get(key)
        if mouse is None:
            return
        self._publish(key, busy=True)
        try:
            fn(mouse)
            self._publish(key, busy=False, error=None)
        except DeviceGone:
            log.info("%s disappeared", key)
            self._forget(key)
        except PermissionError:
            self._publish(key, busy=False, no_permission=True)
        except (evision.ProtocolError, OSError, ValueError) as e:
            log.warning("%s: %s failed: %s", key, what, e)
            self._publish(key, busy=False, error=f"{what} failed: {e}")
            self.failed.emit(key, f"{what} failed: {e}")

    def _forget(self, key: str) -> None:
        mouse = self.mice.pop(key, None)
        if mouse:
            mouse.close()
        if self.states.pop(key, None) is not None:
            self.removed.emit(key)

    def _status(self, mouse: Mouse, full: bool) -> Status:
        st = mouse.status(full=full)
        old = self.states[mouse.node.path].status
        if not full and old is not None and st.online:
            st.config_id, st.model = old.config_id, old.model
            st.mouse_firmware, st.receiver_firmware = old.mouse_firmware, old.receiver_firmware
        if self.fake_battery is not None and st.online:
            st.battery = self.fake_battery
        return st

    def _load(self, mouse: Mouse, full: bool) -> None:
        key = mouse.node.path
        st = self._status(mouse, full)
        settings = None
        if st.online:
            block = mouse.read_config()
            settings = evision.decode_config(block)
            label = st.model.name if st.model else mouse.product.name
            if not storage.has_backup(label):
                log.info("backed up settings to %s", storage.backup_config(label, block))
        self._publish(key, status=st, settings=settings)

    # -- slots -----------------------------------------------------------------------------------

    @Slot()
    def start(self) -> None:
        self.battery_timer = QTimer(self)
        self.battery_timer.timeout.connect(self.tick)
        self.battery_timer.start(BATTERY_INTERVAL_MS)
        self.asleep_timer = QTimer(self)
        self.asleep_timer.timeout.connect(self.wake_check)
        self.asleep_timer.start(ASLEEP_INTERVAL_MS)
        self.event_timer = QTimer(self)
        self.event_timer.timeout.connect(self.pump_events)
        self.event_timer.start(EVENT_PUMP_MS)
        self.scan()

    @Slot()
    def scan(self) -> None:
        found = {f.node.path: f for f in find()}
        for key in list(self.mice):
            if key not in found:
                self._forget(key)
        for key, f in found.items():
            if key in self.mice:
                continue
            self._add(f)

    def _add(self, f: Found) -> None:
        key = f.node.path
        self.mice[key] = Mouse(f, on_event=self._on_event(key))
        self.states[key] = DeviceState(key=key, product_name=f.product.name, link=f.product.link)
        if not os.access(key, os.R_OK | os.W_OK):
            self._publish(key, no_permission=True)
            return
        self._run(key, "Reading the mouse", lambda m: self._load(m, full=True))

    @Slot(str, bool)
    def refresh(self, key: str, with_settings: bool) -> None:
        keys = [key] if key else list(self.mice)
        for k in keys:
            state = self.states.get(k)
            if state is None or state.no_permission:
                continue
            if with_settings or not state.online:
                full = not state.online or state.model is None  # model/firmware only when (re)connecting
                self._run(k, "Reading the mouse", lambda m, full=full: self._load(m, full=full))
            else:
                self._run(k, "Reading the battery", lambda m: self._publish(m.node.path, status=self._status(m, False)))

    @Slot()
    def tick(self) -> None:
        for key, state in list(self.states.items()):
            if state.online:
                self.refresh(key, False)

    @Slot()
    def wake_check(self) -> None:
        """Poll asleep (receiver) mice more often, so the window comes alive soon after a wiggle."""
        for key, state in list(self.states.items()):
            if not state.online and not state.no_permission and not state.busy:
                self.refresh(key, True)

    @Slot()
    def pump_events(self) -> None:
        for key, mouse in list(self.mice.items()):
            try:
                mouse.pump_events()
            except DeviceGone:
                self._forget(key)
            except OSError:
                pass
        for key in list(self._pending_events):
            self._pending_events.discard(key)
            self.refresh(key, True)

    @Slot(str, object, str)
    def apply(self, key: str, change: Callable[[evision.Settings], evision.Settings], what: str) -> None:
        def do(mouse: Mouse) -> None:
            try:
                settings = mouse.apply(change)
            except WriteMismatch:
                self._publish(key, settings=mouse.read_settings())
                raise
            except (evision.ProtocolError, ValueError):
                try:  # show what the mouse really has now
                    self._publish(key, settings=mouse.read_settings())
                except evision.ProtocolError:
                    pass
                raise
            self._publish(key, settings=settings)

        self._run(key, what, do)

    @Slot(str)
    def factory_reset(self, key: str) -> None:
        self._run(key, "Factory reset", lambda m: self._publish(key, settings=m.factory_reset()))

    @Slot()
    def stop(self) -> None:
        for key in list(self.mice):
            self.mice.pop(key).close()


class DeviceManager(QObject):
    """GUI-thread facade. Connect to `changed` and read `states`."""

    changed = Signal(str)  # key ("" = device list changed)
    error = Signal(str, str)  # key, message

    _scan = Signal()
    _refresh = Signal(str, bool)
    _apply = Signal(str, object, str)
    _reset = Signal(str)
    _stop = Signal()

    def __init__(self, fake_battery: int | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self.states: dict[str, DeviceState] = {}
        self._thread = QThread()
        self._thread.setObjectName("aulaar-io")
        self._worker = _Worker(fake_battery)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.start)
        self._worker.stateChanged.connect(self._on_state)
        self._worker.removed.connect(self._on_removed)
        self._worker.failed.connect(self.error)
        self._scan.connect(self._worker.scan)
        self._refresh.connect(self._worker.refresh)
        self._apply.connect(self._worker.apply)
        self._reset.connect(self._worker.factory_reset)
        self._stop.connect(self._worker.stop)
        self._scan_debounce = QTimer(self, singleShot=True, interval=800)
        self._scan_debounce.timeout.connect(self._scan.emit)
        self._udev_notifier: QSocketNotifier | None = None

    def start(self) -> None:
        self._watch_udev()
        self._thread.start()

    def shutdown(self) -> None:
        self._stop.emit()
        self._thread.quit()
        self._thread.wait(3000)

    def _watch_udev(self) -> None:
        try:
            import pyudev
        except ImportError:
            log.warning("pyudev missing: hotplug detection falls back to a 5 s rescan")
            timer = QTimer(self, interval=5000)
            timer.timeout.connect(self._scan.emit)
            timer.start()
            return
        context = pyudev.Context()
        self._monitor = pyudev.Monitor.from_netlink(context)
        self._monitor.filter_by("hidraw")
        self._monitor.start()
        self._udev_notifier = QSocketNotifier(self._monitor.fileno(), QSocketNotifier.Read, self)
        self._udev_notifier.activated.connect(self._on_udev)

    def _on_udev(self) -> None:
        while (device := self._monitor.poll(timeout=0)) is not None:
            log.debug("udev %s %s", device.action, device.device_node)
        self._scan_debounce.start()

    def _on_state(self, state: DeviceState) -> None:
        is_new = state.key not in self.states
        self.states[state.key] = state
        self.changed.emit("" if is_new else state.key)

    def _on_removed(self, key: str) -> None:
        self.states.pop(key, None)
        self.changed.emit("")

    # -- requests from the UI ---------------------------------------------------------------------

    def rescan(self) -> None:
        self._scan.emit()

    def refresh(self, key: str = "", with_settings: bool = True) -> None:
        self._refresh.emit(key, with_settings)

    def apply(self, key: str, change: Callable[[evision.Settings], evision.Settings], what: str = "Saving") -> None:
        self._apply.emit(key, change, what)

    def factory_reset(self, key: str) -> None:
        self._reset.emit(key)

    def preferred(self) -> DeviceState | None:
        """The device to show by default: online first, wired before receiver."""
        states = sorted(self.states.values(), key=lambda s: (not s.online, s.link != evision.WIRED, s.key))
        return states[0] if states else None
