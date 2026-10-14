import random
import unittest
from dataclasses import replace

from aulaar.device import Mouse, WriteMismatch
from aulaar.devices import Found, PRODUCTS
from aulaar.hidraw import HidrawNode
from aulaar.protocol import evision

from .fake_device import FakeEvision


def chunk_headers(fake, cmd):
    return [(p[3], p[4] | p[5] << 8) for p in fake.sent if p[2] == cmd]


class TransportTest(unittest.TestCase):
    def test_wired_read_uses_56_byte_chunks(self):
        fake = FakeEvision()
        data = evision.Transport(fake, evision.WIRED).read_block(evision.CMD_READ_CONFIG, 128)
        self.assertEqual(data, bytes(range(128)))
        self.assertEqual(chunk_headers(fake, evision.CMD_READ_CONFIG), [(56, 0), (56, 56), (16, 112)])
        self.assertEqual(fake.sent[0][:4], bytes([0, 0, evision.CMD_BEGIN, 56]))
        self.assertEqual(fake.sent[-1][:4], bytes([0, 0, evision.CMD_END, 56]))

    def test_wireless_read_uses_24_byte_chunks(self):
        fake = FakeEvision()
        evision.Transport(fake, evision.WIRELESS).read_block(evision.CMD_READ_CONFIG, 128)
        self.assertEqual(
            chunk_headers(fake, evision.CMD_READ_CONFIG),
            [(24, 0), (24, 24), (24, 48), (24, 72), (24, 96), (8, 120)],
        )
        self.assertEqual(fake.sent[0][3], 24)

    def test_write_sends_payload_after_header(self):
        fake = FakeEvision(bytes(128))
        payload = bytes(range(1, 129))
        echo = evision.Transport(fake, evision.WIRED).write_block(evision.CMD_WRITE_CONFIG, payload)
        self.assertEqual(echo, payload)
        self.assertEqual(bytes(fake.config), payload)
        first = [p for p in fake.sent if p[2] == evision.CMD_WRITE_CONFIG][0]
        self.assertEqual(first[:7], bytes([0, 0, 6, 56, 0, 0, 0]))
        self.assertEqual(first[7:63], payload[:56])

    def test_events_are_dispatched_not_taken_as_replies(self):
        fake = FakeEvision()
        events = []
        t = evision.Transport(fake, evision.WIRED, on_event=lambda name, data: events.append(name))
        fake.push_event(b"\x01\x04")
        self.assertEqual(t.command(evision.CMD_BATTERY)[7], 77)
        self.assertEqual(events, ["profile-switch"])

    def test_no_reply_raises(self):
        fake = FakeEvision(online=None)
        t = evision.Transport(fake, evision.WIRELESS, timeout=0.01)
        with self.assertRaises(evision.NoReply):
            t.command(evision.CMD_ONLINE, retries=1)


class ConfigCodecTest(unittest.TestCase):
    def test_round_trip_is_lossless(self):
        rng = random.Random(1)
        for _ in range(200):
            block = bytes(rng.randrange(256) for _ in range(128))
            self.assertEqual(evision.encode_config(evision.decode_config(block), block), block)

    def test_field_encodings(self):
        base = bytes(128)
        s = evision.decode_config(base)
        s.sensor_rotation = -15
        s.sleep_seconds = 600
        s.stages[2] = evision.DpiStage(True, True, 26000, 42000, (1, 2, 3))
        s.lighting = replace(s.lighting, mode=evision.LIGHT_WAVE, colorful=True, direction=2, color=(9, 8, 7))
        b = evision.encode_config(s, base)
        self.assertEqual(b[evision.OFF_ROTATION], 0xF1)
        self.assertEqual(b[68:70], bytes([0x58, 0x02]))
        o = evision.OFF_STAGES + 2 * evision.STAGE_SIZE
        self.assertEqual(b[o : o + 9], bytes([1, 1, 0x90, 0x65, 0x10, 0xA4, 1, 2, 3]))
        self.assertEqual(b[1:9], bytes([4, 0, 0, 2, 1, 9, 8, 7]))
        self.assertEqual(evision.decode_config(b).sensor_rotation, -15)

    def test_validate(self):
        s = evision.decode_config(bytes(128))
        self.assertIn("sleep 0s", evision.validate(s))
        s.sleep_seconds, s.debounce_ms, s.lighting.direction = 300, 4, 1
        for st in s.stages:
            st.x = st.y = 800
        self.assertEqual(evision.validate(s), [])
        self.assertEqual(evision.snap_dpi(1234), 1250)
        self.assertEqual(evision.snap_dpi(99999), 42000)


def valid_block():
    s = evision.decode_config(bytes(128))
    s.sleep_seconds, s.debounce_ms, s.lighting.direction = 300, 4, 1
    for st in s.stages:
        st.x = st.y = 800
    block = bytearray(evision.encode_config(s, bytes(128)))
    block[100:128] = b"unknown-bytes-must-survive!!"  # undefined region
    return bytes(block)


def mouse_for(fake, pid=0x22B7):
    node = HidrawNode("/dev/null", 3, 0x320F, pid, "x", "p/input1", 1)
    m = Mouse(Found(node, PRODUCTS[pid]))
    m._dev = fake
    m._transport = evision.Transport(fake, PRODUCTS[pid].link, timeout=0.01)
    return m


class MouseTest(unittest.TestCase):
    def test_status(self):
        st = mouse_for(FakeEvision(), 0x22A0).status()
        self.assertTrue(st.online)
        self.assertEqual((st.battery, st.config_id, st.model.name), (77, 5, "AULA V9 Ultra+"))
        self.assertEqual(st.mouse_firmware, "1.0.0.5")
        self.assertEqual(st.receiver_firmware, "0.1.2.3")

    def test_asleep_through_receiver(self):
        self.assertFalse(mouse_for(FakeEvision(online=0), 0x22A0).status().online)
        self.assertFalse(mouse_for(FakeEvision(online=None), 0x22A0).is_online())

    def test_apply_changes_only_the_right_byte(self):
        base = valid_block()
        for pid, offset in ((0x22B7, evision.OFF_POLLING_WIRED), (0x22A0, evision.OFF_POLLING_WIRELESS)):
            fake = FakeEvision(base)
            m = mouse_for(fake, pid)
            m.apply(lambda s: s.with_polling(m.link, 6))
            changed = [i for i in range(128) if fake.config[i] != base[i]]
            self.assertEqual(changed, [offset])
            self.assertEqual(fake.config[offset], 6)

    def test_apply_refuses_invalid_values(self):
        fake = FakeEvision(valid_block())
        with self.assertRaises(ValueError):
            mouse_for(fake).apply(lambda s: replace(s, debounce_ms=3))
        self.assertEqual(bytes(fake.config), valid_block())

    def test_apply_detects_bad_echo(self):
        fake = FakeEvision(valid_block(), echo_corrupt=True)
        with self.assertRaises(WriteMismatch):
            mouse_for(fake).apply(lambda s: replace(s, motion_sync=True))


if __name__ == "__main__":
    unittest.main()
