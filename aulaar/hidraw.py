"""Minimal Linux hidraw access using only the standard library.

Enumeration reads sysfs (/sys/class/hidraw/*/device/{uevent,report_descriptor}); I/O is plain
read()/write() on /dev/hidrawN. For numbered reports the first byte of every write and read is the
report ID, so a 63-byte report 4 is written as 64 bytes: [0x04] + data.
"""

from __future__ import annotations

import errno
import os
import re
import select
from dataclasses import dataclass, field

SYSFS_HIDRAW = "/sys/class/hidraw"
BUS_USB = 0x03


class DeviceGone(OSError):
    """The hidraw node disappeared (unplugged) or became unusable."""


@dataclass(frozen=True)
class Collection:
    usage_page: int
    usage: int


@dataclass(frozen=True)
class HidrawNode:
    path: str  # /dev/hidrawN
    bus: int
    vid: int
    pid: int
    name: str  # HID_NAME, e.g. "RealTek AULA-V9Ultra+"
    phys: str  # HID_PHYS, e.g. "usb-0000:00:14.0-2.3.1/input1"
    interface: int | None
    collections: tuple[Collection, ...] = field(default=())

    def has_collection(self, usage_page: int, usage: int) -> bool:
        return Collection(usage_page, usage) in self.collections

    @property
    def usb_device_key(self) -> str:
        """Identifies the physical USB device, shared by all its interfaces."""
        return self.phys.rsplit("/", 1)[0]


def application_collections(descriptor: bytes) -> tuple[Collection, ...]:
    """Return (usage page, usage) of every top-level application collection in a report descriptor."""
    out: list[Collection] = []
    usage_page = 0
    usages: list[tuple[int, int]] = []
    depth = 0
    i = 0
    while i < len(descriptor):
        prefix = descriptor[i]
        if prefix == 0xFE:  # long item: 0xFE, size, tag, data
            if i + 1 >= len(descriptor):
                break
            i += 3 + descriptor[i + 1]
            continue
        size = (0, 1, 2, 4)[prefix & 0x03]
        item_type = (prefix >> 2) & 0x03
        tag = prefix >> 4
        data = int.from_bytes(descriptor[i + 1 : i + 1 + size], "little")
        i += 1 + size
        if item_type == 1 and tag == 0x0:  # global: Usage Page
            usage_page = data
        elif item_type == 2 and tag == 0x0:  # local: Usage
            usages.append((data >> 16, data & 0xFFFF) if size == 4 else (usage_page, data))
        elif item_type == 0:  # main item
            if tag == 0xA:  # Collection
                if depth == 0 and data == 0x01 and usages:
                    out.append(Collection(*usages[0]))
                depth += 1
            elif tag == 0xC:  # End Collection
                depth = max(depth - 1, 0)
            usages = []
    return tuple(out)


def _parse_uevent(text: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


def enumerate_nodes(sysfs: str = SYSFS_HIDRAW) -> list[HidrawNode]:
    nodes: list[HidrawNode] = []
    try:
        entries = sorted(os.listdir(sysfs), key=lambda n: int(re.sub(r"\D", "", n) or 0))
    except FileNotFoundError:
        return nodes
    for entry in entries:
        dev_dir = os.path.join(sysfs, entry, "device")
        try:
            with open(os.path.join(dev_dir, "uevent")) as f:
                uevent = _parse_uevent(f.read())
            with open(os.path.join(dev_dir, "report_descriptor"), "rb") as f:
                descriptor = f.read()
        except OSError:
            continue
        hid_id = uevent.get("HID_ID", "")
        m = re.fullmatch(r"([0-9A-Fa-f]+):([0-9A-Fa-f]+):([0-9A-Fa-f]+)", hid_id)
        if not m:
            continue
        phys = uevent.get("HID_PHYS", "")
        iface = re.search(r"/input(\d+)$", phys)
        nodes.append(
            HidrawNode(
                path=os.path.join("/dev", entry),
                bus=int(m.group(1), 16),
                vid=int(m.group(2), 16),
                pid=int(m.group(3), 16),
                name=uevent.get("HID_NAME", ""),
                phys=phys,
                interface=int(iface.group(1)) if iface else None,
                collections=application_collections(descriptor),
            )
        )
    return nodes


class HidrawDevice:
    """An open /dev/hidrawN. Not thread-safe; callers serialize access."""

    def __init__(self, path: str):
        self.path = path
        try:
            self._fd: int | None = os.open(path, os.O_RDWR | os.O_NONBLOCK | os.O_CLOEXEC)
        except FileNotFoundError as e:
            raise DeviceGone(errno.ENODEV, f"{path} is gone") from e

    def fileno(self) -> int:
        if self._fd is None:
            raise DeviceGone(errno.EBADF, f"{self.path} is closed")
        return self._fd

    def write(self, report: bytes) -> None:
        try:
            os.write(self.fileno(), report)
        except OSError as e:
            if e.errno in (errno.ENODEV, errno.EIO, errno.EPIPE, errno.ESHUTDOWN):
                raise DeviceGone(e.errno, f"{self.path}: {e.strerror}") from e
            raise

    def read(self, timeout: float) -> bytes | None:
        """Read one input report, or return None after `timeout` seconds."""
        fd = self.fileno()
        try:
            ready, _, _ = select.select([fd], [], [], max(timeout, 0))
            if not ready:
                return None
            return os.read(fd, 1024)
        except BlockingIOError:
            return None
        except OSError as e:
            if e.errno in (errno.ENODEV, errno.EIO, errno.ESHUTDOWN):
                raise DeviceGone(e.errno, f"{self.path}: {e.strerror}") from e
            raise

    def drain(self) -> list[bytes]:
        """Return every input report already queued, without waiting."""
        reports = []
        while (report := self.read(0)) is not None:
            reports.append(report)
        return reports

    def close(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            finally:
                self._fd = None

    def __enter__(self) -> HidrawDevice:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
