import unittest

from aulaar import devices, hidraw
from aulaar.protocol import evision

# Report descriptors read from the real AULA-8K Dongle / V9 Ultra+ (identical on both).
IFACE1 = bytes.fromhex(
    "05010906a10185077501950815002501050719e029e781027501950505081901"
    "2905910275039501910375089506150026ff000507190029ff8100c00601ff09"
    "01a101851075089504150026ff00190029ff8102c0050c0901a1018503751095"
    "01150026ff1f19002aff1f8100c0061cff0992a101850419002aff00150026ff"
    "007508953f910019002aff008100c005010980a1018502198129831500250175"
    "0195038102750595018101c0"
)
IFACE2 = bytes.fromhex(
    "060bff0a0401a101150026ff007508953c852a096082020109619202010962b2"
    "0201852b0965b20201170000008027ffffff7f75209504852c19662969810285"
    "2d198a298d8102198e29919102c00602ff0901a1018514190029ff150026ff00"
    "75089514b102c0"
)
IFACE0 = bytes.fromhex(
    "05010902a10185010901a1000509190129051500250195057501810295017503"
    "810105010930093116018026ff7f75109502810609381581257f750895018106"
    "050c0a38021581257f750895018106c0c0"
)


def node(pid, iface, desc):
    return hidraw.HidrawNode(
        path=f"/dev/hidraw-{pid:x}-{iface}", bus=3, vid=0x320F, pid=pid, name="x",
        phys=f"usb-0000:00:14.0-2/input{iface}", interface=iface,
        collections=hidraw.application_collections(desc),
    )


class DescriptorTest(unittest.TestCase):
    def test_config_interface_has_vendor_collection(self):
        cols = hidraw.application_collections(IFACE1)
        self.assertIn(hidraw.Collection(evision.USAGE_PAGE, evision.USAGE), cols)
        self.assertIn(hidraw.Collection(0x01, 0x06), cols)  # keyboard

    def test_other_interfaces_do_not(self):
        for desc in (IFACE0, IFACE2):
            cols = hidraw.application_collections(desc)
            self.assertNotIn(hidraw.Collection(evision.USAGE_PAGE, evision.USAGE), cols)
        self.assertIn(hidraw.Collection(0xFF0B, 0x0104), hidraw.application_collections(IFACE2))

    def test_find_picks_interface_one_only(self):
        nodes = [node(pid, i, d) for pid in (0x22A0, 0x22B7) for i, d in enumerate((IFACE0, IFACE1, IFACE2))]
        nodes.append(node(0x5088, 1, IFACE1))  # other vendor product with the same layout
        found = devices.find(nodes)
        self.assertEqual([(f.node.pid, f.node.interface) for f in found], [(0x22A0, 1), (0x22B7, 1)])
        self.assertEqual(found[0].product.link, evision.WIRELESS)
        self.assertEqual(found[1].product.link, evision.WIRED)


if __name__ == "__main__":
    unittest.main()
