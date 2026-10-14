"""Tray presence that stays out of the way.

Qt's QSystemTrayIcon is always "Active", which KDE shows permanently next to the clock. We publish our
own org.kde.StatusNotifierItem instead, so the item can be "Passive" (KDE keeps it in the hidden tray
popup) and only become "NeedsAttention" (visible) when the battery runs low. dbus-python is driven by
the GLib main loop that Qt's event dispatcher already runs on Linux.
"""

from __future__ import annotations

import array
import logging
import os
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from . import icons

log = logging.getLogger(__name__)

SNI_IFACE = "org.kde.StatusNotifierItem"
WATCHER_NAME = "org.kde.StatusNotifierWatcher"
WATCHER_PATH = "/StatusNotifierWatcher"
MENU_IFACE = "com.canonical.dbusmenu"
ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/MenuBar"

MENU_OPEN, MENU_INFO, MENU_SEP, MENU_REFRESH, MENU_QUIT = 1, 2, 3, 4, 5


class TrayState:
    def __init__(self) -> None:
        self.title = "Aulaar"
        self.subtitle = "No AULA mouse connected"
        self.level: int | None = None
        self.asleep = False
        self.attention = False


class Tray(QObject):
    """Facade used by the app; picks the SNI backend or falls back to QSystemTrayIcon."""

    activated = Signal()
    refreshRequested = Signal()
    quitRequested = Signal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.state = TrayState()
        self._backend: _SniBackend | _QtBackend
        try:
            self._backend = _SniBackend(self)
            log.info("tray: StatusNotifierItem (passive until the battery is low)")
        except Exception as e:  # no session bus, no watcher, no dbus-python …
            log.info("tray: falling back to QSystemTrayIcon (%s)", e)
            self._backend = _QtBackend(self)

    def update(self, *, title: str, subtitle: str, level: int | None, asleep: bool, attention: bool) -> None:
        s = self.state
        changed = (s.title, s.subtitle, s.level, s.asleep, s.attention) != (title, subtitle, level, asleep, attention)
        s.title, s.subtitle, s.level, s.asleep, s.attention = title, subtitle, level, asleep, attention
        if changed:
            self._backend.refresh()


# -- StatusNotifierItem ---------------------------------------------------------------------------


def _ensure_glib_dispatch() -> None:
    """dbus-python needs the default GLib context iterated; Qt does that unless built without GLib."""
    from PySide6.QtCore import QAbstractEventDispatcher

    dispatcher = QAbstractEventDispatcher.instance()
    name = dispatcher.metaObject().className() if dispatcher else ""
    if "Glib" in name:
        return
    from gi.repository import GLib

    ctx = GLib.MainContext.default()
    timer = QTimer(QAbstractEventDispatcher.instance())
    timer.timeout.connect(lambda: [ctx.iteration(False) for _ in range(20) if ctx.pending()])
    timer.start(30)
    log.debug("event dispatcher %s is not GLib-based; pumping GLib from a timer", name)


def _pixmaps(level: int | None, asleep: bool):
    import dbus

    out = []
    for size in (22, 32, 48, 64):
        img = icons.tray_image(size, level, asleep).convertToFormat(QImage.Format_ARGB32)
        words = array.array("I", bytes(img.constBits())[: size * size * 4])
        if words.itemsize == 4 and array.array("I", [1]).tobytes()[0] == 1:  # little endian host
            words.byteswap()  # SNI wants ARGB32 in network byte order
        out.append(dbus.Struct((dbus.Int32(size), dbus.Int32(size), dbus.ByteArray(words.tobytes())), signature="iiay"))
    return dbus.Array(out, signature="(iiay)")


class _SniBackend:
    def __init__(self, tray: Tray):
        import dbus
        import dbus.service
        from dbus.mainloop.glib import DBusGMainLoop

        DBusGMainLoop(set_as_default=True)
        _ensure_glib_dispatch()
        self.tray = tray
        self.bus = dbus.SessionBus()
        if not self.bus.name_has_owner(WATCHER_NAME):
            raise RuntimeError("no StatusNotifierWatcher on the session bus")
        self.name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        self._bus_name = dbus.service.BusName(self.name, self.bus)
        self.item = _make_item_class()(self, self.bus)
        self.menu = _make_menu_class()(self, self.bus)
        self._register()
        self.bus.add_signal_receiver(
            self._watcher_changed, "NameOwnerChanged", "org.freedesktop.DBus", arg0=WATCHER_NAME
        )

    def _register(self) -> None:
        watcher = self.bus.get_object(WATCHER_NAME, WATCHER_PATH)
        watcher.RegisterStatusNotifierItem(self.name, dbus_interface=WATCHER_NAME)

    def _watcher_changed(self, name, old, new) -> None:
        if new:  # plasmashell restarted
            QTimer.singleShot(500, self._register)

    def refresh(self) -> None:
        self.item.NewIcon()
        self.item.NewAttentionIcon()
        self.item.NewToolTip()
        self.item.NewTitle()
        self.item.NewStatus(self.item.status())
        self.menu.bump()


def _make_item_class():
    import dbus
    import dbus.service

    class Item(dbus.service.Object):
        def __init__(self, backend: _SniBackend, bus):
            super().__init__(bus, ITEM_PATH)
            self.backend = backend

        @property
        def state(self) -> TrayState:
            return self.backend.tray.state

        def status(self) -> str:
            return "NeedsAttention" if self.state.attention else "Passive"

        def props(self) -> dict:
            s = self.state
            pix = _pixmaps(s.level, s.asleep)
            return {
                "Category": "Hardware",
                "Id": "aulaar",
                "Title": "Aulaar",
                "Status": self.status(),
                "WindowId": dbus.Int32(0),
                "IconName": "",
                "IconPixmap": pix,
                "OverlayIconName": "",
                "OverlayIconPixmap": dbus.Array([], signature="(iiay)"),
                "AttentionIconName": "",
                "AttentionIconPixmap": pix,
                "AttentionMovieName": "",
                "ToolTip": dbus.Struct(("", dbus.Array([], signature="(iiay)"), s.title, s.subtitle), signature="sa(iiay)ss"),
                "ItemIsMenu": dbus.Boolean(False),
                "Menu": dbus.ObjectPath(MENU_PATH),
            }

        @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature="ss", out_signature="v")
        def Get(self, interface, prop):
            return self.props()[prop]

        @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature="s", out_signature="a{sv}")
        def GetAll(self, interface):
            return dbus.Dictionary(self.props(), signature="sv")

        @dbus.service.method(SNI_IFACE, in_signature="ii")
        def Activate(self, x, y):
            self.backend.tray.activated.emit()

        @dbus.service.method(SNI_IFACE, in_signature="ii")
        def SecondaryActivate(self, x, y):
            self.backend.tray.refreshRequested.emit()

        @dbus.service.method(SNI_IFACE, in_signature="ii")
        def ContextMenu(self, x, y):
            pass  # the host shows our dbusmenu

        @dbus.service.method(SNI_IFACE, in_signature="is")
        def Scroll(self, delta, orientation):
            pass

        @dbus.service.signal(SNI_IFACE)
        def NewIcon(self):
            pass

        @dbus.service.signal(SNI_IFACE)
        def NewAttentionIcon(self):
            pass

        @dbus.service.signal(SNI_IFACE)
        def NewToolTip(self):
            pass

        @dbus.service.signal(SNI_IFACE)
        def NewTitle(self):
            pass

        @dbus.service.signal(SNI_IFACE, signature="s")
        def NewStatus(self, status):
            pass

    return Item


def _make_menu_class():
    import dbus
    import dbus.service

    class Menu(dbus.service.Object):
        def __init__(self, backend: _SniBackend, bus):
            super().__init__(bus, MENU_PATH)
            self.backend = backend
            self.revision = 1

        def items(self) -> list[tuple[int, dict]]:
            s = self.backend.tray.state
            return [
                (MENU_OPEN, {"label": "Open Aulaar"}),
                (MENU_INFO, {"label": f"{s.title} — {s.subtitle}", "enabled": False}),
                (MENU_SEP, {"type": "separator"}),
                (MENU_REFRESH, {"label": "Refresh"}),
                (MENU_QUIT, {"label": "Quit", "icon-name": "application-exit"}),
            ]

        def _node(self, item_id: int, props: dict, children=()):
            return dbus.Struct(
                (dbus.Int32(item_id), dbus.Dictionary(props, signature="sv"), dbus.Array(children, signature="v")),
                signature="ia{sv}av",
            )

        def bump(self) -> None:
            self.revision += 1
            self.LayoutUpdated(dbus.UInt32(self.revision), dbus.Int32(0))

        @dbus.service.method(MENU_IFACE, in_signature="iias", out_signature="u(ia{sv}av)")
        def GetLayout(self, parent_id, depth, prop_names):
            children = [self._node(i, p) for i, p in self.items()]
            root = self._node(0, {"children-display": "submenu"}, children)
            return dbus.UInt32(self.revision), root

        @dbus.service.method(MENU_IFACE, in_signature="aias", out_signature="a(ia{sv})")
        def GetGroupProperties(self, ids, prop_names):
            table = dict(self.items())
            return dbus.Array(
                [dbus.Struct((dbus.Int32(i), dbus.Dictionary(table[i], signature="sv")), signature="ia{sv}") for i in ids if i in table],
                signature="(ia{sv})",
            )

        @dbus.service.method(MENU_IFACE, in_signature="is", out_signature="v")
        def GetProperty(self, item_id, name):
            return dict(self.items()).get(item_id, {}).get(name, "")

        @dbus.service.method(MENU_IFACE, in_signature="isvu")
        def Event(self, item_id, event_id, data, timestamp):
            if event_id == "clicked" and int(item_id) in (MENU_OPEN, MENU_REFRESH, MENU_QUIT):
                _emit(self.backend.tray, int(item_id))

        @dbus.service.method(MENU_IFACE, in_signature="a(isvu)", out_signature="ai")
        def EventGroup(self, events):
            for item_id, event_id, data, ts in events:
                self.Event(item_id, event_id, data, ts)
            return dbus.Array([], signature="i")

        @dbus.service.method(MENU_IFACE, in_signature="i", out_signature="b")
        def AboutToShow(self, item_id):
            return False

        @dbus.service.method(MENU_IFACE, in_signature="ai", out_signature="aiai")
        def AboutToShowGroup(self, ids):
            return dbus.Array([], signature="i"), dbus.Array([], signature="i")

        @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature="ss", out_signature="v")
        def Get(self, interface, prop):
            return self._menu_props()[prop]

        @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature="s", out_signature="a{sv}")
        def GetAll(self, interface):
            return dbus.Dictionary(self._menu_props(), signature="sv")

        def _menu_props(self) -> dict:
            return {
                "Version": dbus.UInt32(3),
                "TextDirection": "ltr",
                "Status": "normal",
                "IconThemePath": dbus.Array([], signature="s"),
            }

        @dbus.service.signal(MENU_IFACE, signature="ui")
        def LayoutUpdated(self, revision, parent):
            pass

        @dbus.service.signal(MENU_IFACE, signature="a(ia{sv})a(ias)")
        def ItemsPropertiesUpdated(self, updated, removed):
            pass

    return Menu


def _emit(tray: Tray, item_id: int) -> None:
    signal: Callable[[], None] = {
        MENU_OPEN: tray.activated.emit,
        MENU_REFRESH: tray.refreshRequested.emit,
        MENU_QUIT: tray.quitRequested.emit,
    }[item_id]
    QTimer.singleShot(0, signal)


# -- Fallback -------------------------------------------------------------------------------------


class _QtBackend:
    def __init__(self, tray: Tray):
        self.tray = tray
        self.icon = QSystemTrayIcon()
        menu = QMenu()
        menu.addAction("Open Aulaar", tray.activated.emit)
        self.info = menu.addAction("")
        self.info.setEnabled(False)
        menu.addSeparator()
        menu.addAction("Refresh", tray.refreshRequested.emit)
        menu.addAction("Quit", tray.quitRequested.emit)
        self.menu = menu
        self.icon.setContextMenu(menu)
        self.icon.activated.connect(
            lambda reason: tray.activated.emit() if reason == QSystemTrayIcon.Trigger else None
        )
        self.refresh()
        self.icon.show()

    def refresh(self) -> None:
        s = self.tray.state
        self.icon.setIcon(icons.tray_icon(s.level, s.asleep))
        self.icon.setToolTip(f"{s.title}\n{s.subtitle}")
        self.info.setText(f"{s.title} — {s.subtitle}")
