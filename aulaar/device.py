"""High-level access to one AULA mouse, either over its cable or through its receiver."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Callable

from . import hidraw
from .devices import Found, Model, model_for
from .protocol import evision

log = logging.getLogger(__name__)


class WriteMismatch(evision.ProtocolError):
    """The device echoed back a config block different from the one written."""


@dataclass
class Status:
    online: bool
    battery: int | None = None  # percent; None when unknown
    battery_raw: bytes = b""
    config_id: int | None = None
    model: Model | None = None
    mouse_firmware: str | None = None
    receiver_firmware: str | None = None


class Mouse:
    """One config interface (wired mouse or receiver). All I/O is serialized by an internal lock."""

    def __init__(self, found: Found, on_event: Callable[[str, bytes], None] | None = None):
        self.node = found.node
        self.product = found.product
        self._on_event = on_event
        self._lock = threading.RLock()
        self._dev: hidraw.HidrawDevice | None = None
        self._transport: evision.Transport | None = None
        self.config_block: bytes | None = None

    @property
    def link(self) -> int:
        return self.product.link

    @property
    def link_name(self) -> str:
        return "2.4G" if self.link == evision.WIRELESS else "Wired"

    def __repr__(self) -> str:
        return f"<Mouse {self.product.name} {self.node.path}>"

    # -- connection ------------------------------------------------------------------------------

    def open(self) -> None:
        with self._lock:
            if self._dev is None:
                self._dev = hidraw.HidrawDevice(self.node.path)
                self._transport = evision.Transport(self._dev, self.link, on_event=self._on_event)

    def close(self) -> None:
        with self._lock:
            if self._dev is not None:
                self._dev.close()
            self._dev = self._transport = None

    @property
    def transport(self) -> evision.Transport:
        if self._transport is None:
            self.open()
        assert self._transport is not None
        return self._transport

    def fileno(self) -> int | None:
        return self._dev.fileno() if self._dev is not None else None

    def pump_events(self) -> None:
        """Handle input reports that arrived while idle (report-3 events)."""
        with self._lock:
            if self._dev is not None:
                for report in self._dev.drain():
                    self.transport._dispatch_unsolicited(report)

    # -- status ----------------------------------------------------------------------------------

    def is_online(self) -> bool:
        """Wired mice are always online; through the receiver, 0 or no answer means asleep/off."""
        if self.link == evision.WIRED:
            return True
        with self._lock:
            try:
                return self.transport.command(evision.CMD_ONLINE, retries=1)[7] != 0
            except evision.NoReply:
                return False

    def battery(self) -> tuple[int | None, bytes]:
        with self._lock:
            reply = self.transport.command(evision.CMD_BATTERY)
        level = reply[7]
        return (level if 0 < level <= 100 else None), reply

    def config_id(self) -> int:
        with self._lock:
            return self.transport.read_block(evision.CMD_INFO, evision.INFO_SHORT_LEN)[7]

    def mouse_firmware(self) -> str:
        with self._lock:
            info = self.transport.read_block(evision.CMD_INFO, evision.INFO_LONG_LEN)
        return evision.dotted_version(info[20], info[21])

    def receiver_firmware(self) -> str | None:
        if self.link != evision.WIRELESS:
            return None
        with self._lock:
            reply = self.transport.command(evision.CMD_RECEIVER_VERSION)
        return evision.dotted_version(reply[7], reply[8])

    def status(self, full: bool = True) -> Status:
        """Online check, battery, and (if `full`) model and firmware versions."""
        with self._lock:
            if not self.is_online():
                return Status(online=False)
            battery, raw = self.battery()
            st = Status(online=True, battery=battery, battery_raw=raw)
            if full:
                st.config_id = self.config_id()
                st.model = model_for(st.config_id)
                st.mouse_firmware = self.mouse_firmware()
                st.receiver_firmware = self.receiver_firmware()
            return st

    # -- settings --------------------------------------------------------------------------------

    def read_config(self) -> bytes:
        with self._lock:
            self.config_block = self.transport.read_block(evision.CMD_READ_CONFIG, evision.CONFIG_SIZE)
            return self.config_block

    def read_settings(self) -> evision.Settings:
        return evision.decode_config(self.read_config())

    def apply(self, change: Callable[[evision.Settings], evision.Settings]) -> evision.Settings:
        """Read the current block, apply `change` to its decoded form, write it back and verify."""
        with self._lock:
            current = self.read_config()
            new_settings = change(evision.decode_config(current))
            problems = evision.validate(new_settings)
            old_problems = set(evision.validate(evision.decode_config(current)))
            if introduced := [p for p in problems if p not in old_problems]:
                raise ValueError("refusing to write: " + ", ".join(introduced))
            block = evision.encode_config(new_settings, current)
            if block == current:
                return new_settings
            log.info("writing config: %s", _diff(current, block))
            echo = self.transport.write_block(evision.CMD_WRITE_CONFIG, block)
            if echo[: len(block)] != block:
                log.warning("write echo differs: %s", _diff(block, echo))
                self.read_config()
                raise WriteMismatch("the mouse did not confirm the new settings")
            self.config_block = block
            return evision.decode_config(block)

    def factory_reset(self) -> evision.Settings:
        with self._lock:
            self.transport.command(evision.CMD_FACTORY_RESET)
            threading.Event().wait(0.3)
            return self.read_settings()


def _diff(a: bytes, b: bytes) -> str:
    changes = [f"[{i}] {x:02x}->{y:02x}" for i, (x, y) in enumerate(zip(a, b)) if x != y]
    if len(a) != len(b):
        changes.append(f"length {len(a)}->{len(b)}")
    return ", ".join(changes) or "no change"
