"""An in-memory stand-in for an Evision mouse's hidraw node."""

from aulaar.protocol import evision


class FakeEvision:
    def __init__(self, config=None, *, battery=77, config_id=5, online=1, echo_corrupt=False):
        self.config = bytearray(config if config is not None else bytes(range(128)))
        self.battery = battery
        self.config_id = config_id
        self.online = online  # None = never answers the online check
        self.echo_corrupt = echo_corrupt
        self.sent: list[bytes] = []
        self.queue: list[bytes] = []
        self.info = bytearray(22)
        self.info[7] = config_id
        self.info[20], self.info[21] = 0x10, 0x05

    def push_event(self, payload: bytes) -> None:
        self.queue.append(bytes([evision.EVENT_REPORT_ID]) + payload.ljust(16, b"\x00"))

    def write(self, report: bytes) -> None:
        assert report[0] == evision.REPORT_ID and len(report) == 64, report
        d = report[1:]
        self.sent.append(d)
        cmd, length, off = d[2], d[3], d[4] | d[5] << 8
        reply = bytearray(63)
        reply[:7] = d[:7]
        if cmd == evision.CMD_ONLINE:
            if self.online is None:
                return
            reply[7] = self.online
        elif cmd == evision.CMD_BATTERY:
            reply[7] = self.battery
        elif cmd == evision.CMD_RECEIVER_VERSION:
            reply[7], reply[8] = 0x01, 0x23
        elif cmd == evision.CMD_INFO:
            reply[7 : 7 + length] = self.info[off : off + length]
        elif cmd == evision.CMD_READ_CONFIG:
            reply[7 : 7 + length] = self.config[off : off + length]
        elif cmd == evision.CMD_WRITE_CONFIG:
            self.config[off : off + length] = d[7 : 7 + length]
            echo = bytearray(d[7 : 7 + length])
            if self.echo_corrupt and echo:
                echo[0] ^= 0xFF
            reply[7 : 7 + length] = echo
        self.queue.append(bytes([evision.REPORT_ID]) + bytes(reply))

    def read(self, timeout):
        return self.queue.pop(0) if self.queue else None

    def drain(self):
        out, self.queue = self.queue, []
        return out

    def close(self):
        pass

    def fileno(self):
        return -1
