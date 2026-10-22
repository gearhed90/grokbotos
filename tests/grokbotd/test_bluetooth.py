"""bluetooth.*: BlueZ state from busctl JSON, commands built safely."""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "system_files", "usr", "lib", "grokbot"))
from grokbotd import bluetooth as bt  # noqa: E402
from grokbotd.backends import BackendError  # noqa: E402

HP = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_01"
MS = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_02"


def s(v):
    return {"type": "s", "data": v}


def b(v):
    return {"type": "b", "data": v}


def managed(powered=True, hp_paired=True, hp_connected=True):
    return {"type": "a{oa{sa{sv}}}", "data": [{
        "/org/bluez": {"org.bluez.AgentManager1": {}},
        "/org/bluez/hci0": {"org.bluez.Adapter1": {"Address": s("00:1A:7D:DA:71:13"), "Alias": s("grokbot"),
                                                   "Powered": b(powered), "Discovering": b(False),
                                                   "Discoverable": b(False)}},
        HP: {"org.bluez.Device1": {"Address": s("AA:BB:CC:DD:EE:01"), "Alias": s("WH-1000XM4"),
                                   "Icon": s("audio-headset"), "Paired": b(hp_paired), "Trusted": b(hp_paired),
                                   "Connected": b(hp_connected), "Adapter": {"type": "o", "data": "/org/bluez/hci0"}},
             "org.bluez.Battery1": {"Percentage": {"type": "y", "data": 70}}},
        MS: {"org.bluez.Device1": {"Address": s("AA:BB:CC:DD:EE:02"), "Name": s("MX Anywhere"),
                                   "Icon": s("input-mouse"), "Paired": b(False), "RSSI": {"type": "n", "data": -48},
                                   "Adapter": {"type": "o", "data": "/org/bluez/hci0"}}},
    }]}


class BluetoothTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.state = managed()

        def run(cmd, timeout=10):
            self.calls.append(cmd)
            if "GetManagedObjects" in cmd:
                if self.state is None:
                    raise BackendError("bluetooth: the Bluetooth service (bluetoothd) is not running")
                return json.dumps(self.state)
            return ""
        self.p = mock.patch.object(bt, "_run", run)
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def acts(self):
        return [c for c in self.calls if "GetManagedObjects" not in c]

    def test_status(self):
        r = bt.bluetooth_status({})
        self.assertTrue(r["available"] and r["service"] and r["powered"])
        self.assertEqual([d["name"] for d in r["devices"]], ["WH-1000XM4"])  # unpaired mouse not listed
        self.assertEqual(r["devices"][0]["battery_percent"], 70)
        self.assertEqual(r["connected"], ["WH-1000XM4"])

    def test_no_service_no_adapter(self):
        self.state = None
        r = bt.bluetooth_status({})
        self.assertEqual((r["available"], r["service"]), (False, False))
        with self.assertRaises(BackendError):
            bt.bluetooth_set_power({"powered": True})
        self.state = {"type": "x", "data": [{"/org/bluez": {}}]}
        self.assertEqual((bt.bluetooth_status({})["available"], bt.bluetooth_status({})["service"]), (False, True))

    def test_power(self):
        with mock.patch.object(bt.subprocess, "run") as rf:
            bt.bluetooth_set_power({"powered": True})
        self.assertIn(["busctl", "--system", "set-property", "org.bluez", "/org/bluez/hci0",
                       "org.bluez.Adapter1", "Powered", "b", "true"], self.acts())
        bt.bluetooth_set_power({"powered": False})
        self.assertEqual(self.acts()[-1][-1], "false")
        del rf

    def test_scan_lists_unpaired(self):
        r = bt.bluetooth_scan({"seconds": 5})
        self.assertEqual(self.acts()[0], ["bluetoothctl", "--timeout", "5", "scan", "on"])
        self.assertEqual([d["address"] for d in r["devices"]], ["AA:BB:CC:DD:EE:02"])
        self.state = managed(powered=False)
        with self.assertRaises(BackendError):
            bt.bluetooth_scan({})

    def test_pair_trust_connect(self):
        bt.bluetooth_pair({"address": "aa:bb:cc:dd:ee:02"})
        a = self.acts()
        self.assertEqual(a[0][-2:], ["org.bluez.Device1", "Pair"])
        self.assertEqual(a[0][5], MS)
        self.assertEqual(a[1][-3:], ["Trusted", "b", "true"])
        self.assertEqual(a[2][-1], "Connect")

    def test_paired_device_not_repaired(self):
        bt.bluetooth_pair({"address": "AA:BB:CC:DD:EE:01", "connect": False})
        self.assertEqual([c[-3:] for c in self.acts()], [["Trusted", "b", "true"]])

    def test_disconnect_remove_trust(self):
        bt.bluetooth_disconnect({"address": "AA:BB:CC:DD:EE:01"})
        bt.bluetooth_trust({"address": "AA:BB:CC:DD:EE:01", "trusted": False})
        r = bt.bluetooth_remove({"address": "AA:BB:CC:DD:EE:01"})
        a = self.acts()
        self.assertEqual(a[0][-1], "Disconnect")
        self.assertEqual(a[1][-3:], ["Trusted", "b", "false"])
        self.assertEqual(a[2][3:], ["org.bluez", "/org/bluez/hci0", "org.bluez.Adapter1", "RemoveDevice", "o", HP])
        self.assertEqual(r, {"removed": "AA:BB:CC:DD:EE:01"})

    def test_bad_and_unknown_address(self):
        for bad in ("AA:BB:CC:DD:EE", "AA:BB:CC:DD:EE:01; rm", "/org/bluez/hci0", ""):
            with self.assertRaises(BackendError):
                bt.bluetooth_connect({"address": bad})
        with self.assertRaises(BackendError):
            bt.bluetooth_connect({"address": "11:22:33:44:55:66"})
        self.assertEqual(self.acts(), [])

    def test_friendly_errors(self):
        self.assertIn("PIN", bt._friendly("Call failed: org.bluez.Error.AuthenticationFailed"))
        self.assertIn("blocked", bt._friendly("org.bluez.Error.Blocked"))


if __name__ == "__main__":
    unittest.main()
