"""Evision mouse protocol (AULA V9 / X9 families and the AULA-8K Dongle).

Recovered from the AULA HUB web driver's "vision" SDK; see docs/PROTOCOL.md for the full write-up.
All traffic is HID report 4 (63 data bytes) on the vendor collection 0xFF1C/0x92. Byte offsets in
this module index the report *data*, i.e. after the report ID, the same way WebHID does.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, replace
from typing import Callable, Protocol

log = logging.getLogger(__name__)

USAGE_PAGE = 0xFF1C
USAGE = 0x92
REPORT_ID = 0x04
EVENT_REPORT_ID = 0x03
REPORT_LEN = 63

WIRED = 1
WIRELESS = 2
CHUNK_SIZE = {WIRED: 56, WIRELESS: 24}

CMD_BEGIN = 0x01
CMD_END = 0x02
CMD_INFO = 0x03
CMD_READ_CONFIG = 0x05
CMD_WRITE_CONFIG = 0x06
CMD_FACTORY_RESET = 0x0D
CMD_BATTERY = 0x1A
CMD_ONLINE = 0xAA
CMD_RECEIVER_VERSION = 0xB3

INFO_SHORT_LEN = 10  # payload[7] = configId (model)
INFO_LONG_LEN = 22  # payload[20], payload[21] = mouse firmware version
CONFIG_SIZE = 128

# Report-3 event payloads the firmware sends on its own.
EVENTS = {b"\x01\x04": "profile-switch", b"\x02\x04": "reset", b"\xff\xff": "connection-error"}

POLLING_RATES = (125, 250, 500, 1000, 2000, 4000, 8000)
SLEEP_SECONDS = (180, 240, 300, 600, 900, 1200)
DEBOUNCE_MS = (1, 2, 4, 6, 8, 10)
LOD_MM = (1, 2)
LIGHT_MODES = ("Static", "Breathing", "Blink", "Spectrum", "Wave", "Off")
LIGHT_STATIC, LIGHT_BREATHING, LIGHT_BLINK, LIGHT_SPECTRUM, LIGHT_WAVE, LIGHT_OFF = range(6)
COLORFUL_LIGHT_MODES = (LIGHT_SPECTRUM, LIGHT_WAVE)
DPI_LIGHT_MODES = ("Off", "Static", "Breathing")
DPI_LIGHT_OFF, DPI_LIGHT_STATIC, DPI_LIGHT_BREATHING = range(3)
NUM_STAGES = 6
DPI_MIN, DPI_MAX, DPI_STEP = 100, 42000, 50
ROTATION_MIN, ROTATION_MAX = -30, 30

# Config block offsets.
OFF_PROFILE = 0
OFF_LIGHT_MODE = 1
OFF_LIGHT_BRIGHTNESS = 2
OFF_LIGHT_SPEED = 3
OFF_LIGHT_DIRECTION = 4
OFF_LIGHT_COLORFUL = 5
OFF_LIGHT_RGB = 6
OFF_POLLING_WIRELESS = 10
OFF_POLLING_WIRED = 11
OFF_ACTIVE_STAGE = 12
OFF_LOD = 13
OFF_STAGES = 14
STAGE_SIZE = 9
OFF_SLEEP = 68
OFF_DEBOUNCE = 70
OFF_MOTION_SYNC = 71
OFF_ANGLE_SNAP = 72
OFF_ROTATION = 74
OFF_DPI_LIGHT_MODE = 76
OFF_DPI_LIGHT_BRIGHTNESS = 77
OFF_DPI_LIGHT_SPEED = 78


class ProtocolError(Exception):
    pass


class NoReply(ProtocolError):
    """The device did not answer in time (asleep, out of range, or wrong interface)."""


class RawDevice(Protocol):
    def write(self, report: bytes) -> None: ...
    def read(self, timeout: float) -> bytes | None: ...
    def drain(self) -> list[bytes]: ...


def hex_bytes(data: bytes) -> str:
    return " ".join(f"{b:02x}" for b in data)


def dotted_version(*parts: int) -> str:
    """AULA HUB shows versions as every hex digit separated by dots: 0x01, 0x23 -> "0.1.2.3"."""
    return ".".join("".join(f"{p:02X}" for p in parts))


class Transport:
    """Request/response framing over one open hidraw node."""

    def __init__(
        self,
        device: RawDevice,
        link: int,
        *,
        timeout: float = 2.0,
        retries: int = 3,
        on_event: Callable[[str, bytes], None] | None = None,
    ):
        if link not in CHUNK_SIZE:
            raise ValueError(f"unknown link type {link}")
        self.device = device
        self.link = link
        self.chunk = CHUNK_SIZE[link]
        self.timeout = timeout
        self.retries = retries
        self.on_event = on_event

    # -- low level -------------------------------------------------------------------------------

    def _dispatch_unsolicited(self, report: bytes) -> None:
        if report and report[0] == EVENT_REPORT_ID:
            name = EVENTS.get(bytes(report[1:3]))
            if name:
                log.debug("event %s (%s)", name, hex_bytes(report))
                if self.on_event:
                    self.on_event(name, bytes(report[1:]))
                return
        log.debug("ignored report %s", hex_bytes(report[:16]))

    def _exchange(self, data: bytes, cmd: int) -> bytes:
        """Send one report-4 packet and return the data of the next report-4 reply."""
        for stale in self.device.drain():
            self._dispatch_unsolicited(stale)
        packet = bytes([REPORT_ID]) + data.ljust(REPORT_LEN, b"\x00")
        log.debug("-> %s", hex_bytes(packet[:16]))
        self.device.write(packet)
        deadline = time.monotonic() + self.timeout
        while (remaining := deadline - time.monotonic()) > 0:
            report = self.device.read(remaining)
            if report is None:
                break
            if report[0] != REPORT_ID:
                self._dispatch_unsolicited(report)
                continue
            reply = bytes(report[1:])
            log.debug("<- %s", hex_bytes(report[:16]))
            if len(reply) > 2 and reply[2] != cmd:
                log.debug("reply echoes cmd %#04x, expected %#04x", reply[2], cmd)
            return reply
        raise NoReply(f"no reply to command {cmd:#04x}")

    def command(self, cmd: int, *, retries: int | None = None) -> bytes:
        """Simple command: [00 00 cmd L 00 00 ...], L = chunk size of this link."""
        attempts = self.retries if retries is None else retries
        last: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                return self._exchange(bytes([0, 0, cmd, self.chunk, 0, 0]), cmd)
            except NoReply as e:
                last = e
                if attempt < attempts:
                    time.sleep(0.1)
        raise NoReply(f"command {cmd:#04x} failed after {attempts} tries: {last}")

    # -- block transfers -------------------------------------------------------------------------

    def _chunks(self, cmd: int, length: int, payload: bytes | None):
        for offset in range(0, length, self.chunk):
            size = min(self.chunk, length - offset)
            header = bytes([0, 0, cmd, size, offset & 0xFF, offset >> 8, 0])
            body = payload[offset : offset + size] if payload is not None else b""
            yield offset, header + body

    def _transfer(self, cmd: int, length: int, payload: bytes | None) -> bytes:
        self.command(CMD_BEGIN)
        try:
            out = bytearray()
            for _, packet in self._chunks(cmd, length, payload):
                reply = self._exchange(packet, cmd)
                if len(reply) < 7:
                    raise ProtocolError(f"short reply to {cmd:#04x}: {hex_bytes(reply)}")
                out += reply[7 : 7 + reply[3]]
            return bytes(out)
        finally:
            try:
                self.command(CMD_END)
            except ProtocolError as e:
                log.warning("ending transfer %#04x failed: %s", cmd, e)

    def read_block(self, cmd: int, length: int) -> bytes:
        data = self._transfer(cmd, length, None)
        if len(data) < length:
            raise ProtocolError(f"block {cmd:#04x}: got {len(data)} of {length} bytes")
        return data[:length]

    def write_block(self, cmd: int, payload: bytes) -> bytes:
        """Write a block; returns what the device echoed back."""
        return self._transfer(cmd, len(payload), bytes(payload))


# -- config block ---------------------------------------------------------------------------------


@dataclass
class DpiStage:
    enabled: bool = True
    xy_split: bool = False
    x: int = 800
    y: int = 800
    color: tuple[int, int, int] = (255, 255, 255)


@dataclass
class Lighting:
    mode: int = LIGHT_STATIC
    brightness: int = 3
    speed: int = 2
    direction: int = 1
    colorful: bool = False
    color: tuple[int, int, int] = (255, 255, 255)


@dataclass
class DpiLighting:
    mode: int = DPI_LIGHT_STATIC
    brightness: int = 2
    speed: int = 1


@dataclass
class Settings:
    """Decoded config block. Values are kept exactly as stored so decode→encode is lossless."""

    profile: int = 0
    lighting: Lighting = field(default_factory=Lighting)
    polling_wireless: int = 3  # index into POLLING_RATES
    polling_wired: int = 3
    active_stage: int = 0
    lod: int = 0  # index into LOD_MM
    stages: list[DpiStage] = field(default_factory=lambda: [DpiStage() for _ in range(NUM_STAGES)])
    sleep_seconds: int = 300
    debounce_ms: int = 4
    motion_sync: bool = False
    angle_snap: bool = False
    sensor_rotation: int = 0
    dpi_lighting: DpiLighting = field(default_factory=DpiLighting)

    def polling_index(self, link: int) -> int:
        return self.polling_wireless if link == WIRELESS else self.polling_wired

    def with_polling(self, link: int, index: int) -> Settings:
        key = "polling_wireless" if link == WIRELESS else "polling_wired"
        return replace(self, **{key: index})


def _u16(block: bytes, off: int) -> int:
    return block[off] | block[off + 1] << 8


def decode_config(block: bytes) -> Settings:
    if len(block) < CONFIG_SIZE:
        raise ProtocolError(f"config block is {len(block)} bytes, expected {CONFIG_SIZE}")
    b = block
    stages = []
    for i in range(NUM_STAGES):
        o = OFF_STAGES + STAGE_SIZE * i
        stages.append(
            DpiStage(
                enabled=bool(b[o]),
                xy_split=bool(b[o + 1]),
                x=_u16(b, o + 2),
                y=_u16(b, o + 4),
                color=(b[o + 6], b[o + 7], b[o + 8]),
            )
        )
    rotation = b[OFF_ROTATION]
    return Settings(
        profile=b[OFF_PROFILE],
        lighting=Lighting(
            mode=b[OFF_LIGHT_MODE],
            brightness=b[OFF_LIGHT_BRIGHTNESS],
            speed=b[OFF_LIGHT_SPEED],
            direction=b[OFF_LIGHT_DIRECTION],
            colorful=bool(b[OFF_LIGHT_COLORFUL]),
            color=tuple(b[OFF_LIGHT_RGB : OFF_LIGHT_RGB + 3]),
        ),
        polling_wireless=b[OFF_POLLING_WIRELESS],
        polling_wired=b[OFF_POLLING_WIRED],
        active_stage=b[OFF_ACTIVE_STAGE],
        lod=b[OFF_LOD],
        stages=stages,
        sleep_seconds=_u16(b, OFF_SLEEP),
        debounce_ms=b[OFF_DEBOUNCE],
        motion_sync=bool(b[OFF_MOTION_SYNC]),
        angle_snap=bool(b[OFF_ANGLE_SNAP]),
        sensor_rotation=rotation - 256 if rotation > 127 else rotation,
        dpi_lighting=DpiLighting(
            mode=b[OFF_DPI_LIGHT_MODE],
            brightness=b[OFF_DPI_LIGHT_BRIGHTNESS],
            speed=b[OFF_DPI_LIGHT_SPEED],
        ),
    )


def encode_config(settings: Settings, base: bytes) -> bytes:
    """Patch `settings` into a copy of `base`; bytes the protocol doesn't define stay untouched."""
    if len(base) < CONFIG_SIZE:
        raise ProtocolError(f"base block is {len(base)} bytes, expected {CONFIG_SIZE}")
    b = bytearray(base[:CONFIG_SIZE])
    s = settings

    def put16(off: int, value: int) -> None:
        b[off] = value & 0xFF
        b[off + 1] = (value >> 8) & 0xFF

    def put_bool(off: int, value: bool) -> None:
        if bool(b[off]) != bool(value):  # keep the firmware's own non-zero value when unchanged
            b[off] = int(value)

    b[OFF_PROFILE] = s.profile & 0xFF
    lt = s.lighting
    b[OFF_LIGHT_MODE] = lt.mode & 0xFF
    b[OFF_LIGHT_BRIGHTNESS] = lt.brightness & 0xFF
    b[OFF_LIGHT_SPEED] = lt.speed & 0xFF
    b[OFF_LIGHT_DIRECTION] = lt.direction & 0xFF
    put_bool(OFF_LIGHT_COLORFUL, lt.colorful)
    b[OFF_LIGHT_RGB : OFF_LIGHT_RGB + 3] = bytes(c & 0xFF for c in lt.color)
    b[OFF_POLLING_WIRELESS] = s.polling_wireless & 0xFF
    b[OFF_POLLING_WIRED] = s.polling_wired & 0xFF
    b[OFF_ACTIVE_STAGE] = s.active_stage & 0xFF
    b[OFF_LOD] = s.lod & 0xFF
    for i, st in enumerate(s.stages[:NUM_STAGES]):
        o = OFF_STAGES + STAGE_SIZE * i
        put_bool(o, st.enabled)
        put_bool(o + 1, st.xy_split)
        put16(o + 2, st.x)
        put16(o + 4, st.y)
        b[o + 6 : o + 9] = bytes(c & 0xFF for c in st.color)
    put16(OFF_SLEEP, s.sleep_seconds)
    b[OFF_DEBOUNCE] = s.debounce_ms & 0xFF
    put_bool(OFF_MOTION_SYNC, s.motion_sync)
    put_bool(OFF_ANGLE_SNAP, s.angle_snap)
    b[OFF_ROTATION] = s.sensor_rotation & 0xFF
    dl = s.dpi_lighting
    b[OFF_DPI_LIGHT_MODE] = dl.mode & 0xFF
    b[OFF_DPI_LIGHT_BRIGHTNESS] = dl.brightness & 0xFF
    b[OFF_DPI_LIGHT_SPEED] = dl.speed & 0xFF
    return bytes(b) + bytes(base[CONFIG_SIZE:])


def validate(settings: Settings) -> list[str]:
    """Return human-readable problems with values the firmware is known to accept."""
    s, problems = settings, []

    def check(ok: bool, msg: str) -> None:
        if not ok:
            problems.append(msg)

    lt = s.lighting
    check(0 <= lt.mode < len(LIGHT_MODES), f"lighting mode {lt.mode}")
    check(0 <= lt.brightness <= 4, f"lighting brightness {lt.brightness}")
    check(0 <= lt.speed <= 4, f"lighting speed {lt.speed}")
    check(lt.direction in (1, 2), f"lighting direction {lt.direction}")
    for name in ("polling_wireless", "polling_wired"):
        check(0 <= getattr(s, name) < len(POLLING_RATES), f"{name} {getattr(s, name)}")
    check(0 <= s.active_stage < NUM_STAGES, f"active stage {s.active_stage}")
    check(0 <= s.lod < len(LOD_MM), f"LOD {s.lod}")
    for i, st in enumerate(s.stages):
        for axis in ("x", "y"):
            v = getattr(st, axis)
            check(DPI_MIN <= v <= DPI_MAX and v % DPI_STEP == 0, f"stage {i + 1} {axis.upper()} DPI {v}")
    check(s.sleep_seconds in SLEEP_SECONDS, f"sleep {s.sleep_seconds}s")
    check(s.debounce_ms in DEBOUNCE_MS, f"debounce {s.debounce_ms}ms")
    check(ROTATION_MIN <= s.sensor_rotation <= ROTATION_MAX, f"sensor rotation {s.sensor_rotation}")
    dl = s.dpi_lighting
    check(0 <= dl.mode < len(DPI_LIGHT_MODES), f"DPI light mode {dl.mode}")
    check(0 <= dl.brightness <= 2, f"DPI light brightness {dl.brightness}")
    check(0 <= dl.speed <= 2, f"DPI light speed {dl.speed}")
    return problems


def snap_dpi(value: int) -> int:
    value = round(value / DPI_STEP) * DPI_STEP
    return max(DPI_MIN, min(DPI_MAX, value))
