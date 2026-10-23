"""network.connections.* / network.vpn.*: nmcli argv built only from listed UUIDs and validated values."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "system_files", "usr", "lib", "grokbot"))
from grokbotd import netconn  # noqa: E402
from grokbotd.backends import BackendError  # noqa: E402

W = "11111111-2222-3333-4444-555555555555"
V = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
F = "99999999-2222-3333-4444-555555555555"


class NetconnTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.vpn_active = False
        self.conns = ["Wired connection 1:%s:802-3-ethernet:enp1s0:yes:activated" % W,
                      "office:%s:wireguard::no:" % V,
                      "Home\\:Wifi:%s:802-11-wireless:wlp2s0:yes:activated" % F]

        def run(cmd, timeout=10, what=None):
            self.calls.append(cmd)
            if cmd[:3] == ["nmcli", "-t", "-f"] and cmd[-2:] == ["connection", "show"]:
                return "\n".join(self.conns) + "\n"
            if cmd[-1] == "device":
                return "enp1s0:ethernet:connected:Wired connection 1\nwlp2s0:wifi:connected:Home\nlo:loopback:unmanaged:\n"
            if "show" in cmd:
                return ("ipv4.method:auto\nipv4.addresses:\nipv4.gateway:--\nipv4.dns:\n"
                        "IP4.ADDRESS[1]:10.0.2.15/24\n")
            if "import" in cmd:
                self.conns.append("office2:bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee:wireguard::no:")
            return ""
        self.p = mock.patch.object(netconn, "_run", run)
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def acts(self):
        return [c for c in self.calls if c[:3] != ["nmcli", "-t", "-f"]]

    def test_list_wired_and_vpn_only(self):
        r = netconn.network_connections_list({})
        self.assertEqual([c["kind"] for c in r["connections"]], ["wired", "vpn"])
        self.assertEqual(r["connections"][0]["ipv4"]["current"], ["10.0.2.15/24"])
        self.assertEqual(r["wired_devices"][0]["device"], "enp1s0")
        self.assertEqual(r["vpn_active"], [])

    def test_up_down(self):
        netconn.network_connection_up({"uuid": V})
        self.assertEqual(self.acts()[0], ["nmcli", "--wait", "30", "connection", "up", "uuid", V])
        netconn.network_connection_down({"uuid": W})
        self.assertEqual(self.acts()[1], ["nmcli", "connection", "down", "uuid", W])

    def test_wifi_and_unknown_refused(self):
        for u in (F, "not-a-uuid", "00000000-0000-0000-0000-000000000000"):
            with self.assertRaises(BackendError):
                netconn.network_connection_up({"uuid": u})
        self.assertEqual(self.acts(), [])

    def test_configure_manual(self):
        netconn.network_wired_configure({"uuid": W, "ipv4": "manual", "address": "192.168.1.20/24",
                                         "gateway": "192.168.1.1", "dns": ["1.1.1.1", "8.8.8.8"]})
        a = self.acts()[0]
        self.assertEqual(a[:5], ["nmcli", "connection", "modify", "uuid", W])
        self.assertEqual(a[5:], ["ipv4.method", "manual", "ipv4.addresses", "192.168.1.20/24",
                                 "ipv4.gateway", "192.168.1.1", "ipv4.dns", "1.1.1.1,8.8.8.8"])
        self.assertEqual(self.acts()[1][-3:], ["up", "uuid", W])  # active -> reapplied

    def test_configure_rejects_bad_values(self):
        bad = [{"address": "192.168.1.20"}, {"address": "192.168.1.0/24"}, {"address": "x; reboot"},
               {"address": "192.168.1.20/24", "gateway": "10.0.0.1"},
               {"address": "192.168.1.20/24", "dns": ["evil"]}]
        for b in bad:
            with self.assertRaises(BackendError):
                netconn.network_wired_configure(dict(uuid=W, ipv4="manual", **b))
        with self.assertRaises(BackendError):
            netconn.network_wired_configure({"uuid": V, "ipv4": "auto"})  # VPN is not wired
        self.assertEqual(self.acts(), [])

    def test_vpn_import_from_home_only(self):
        home = tempfile.mkdtemp()
        os.makedirs(os.path.join(home, "Downloads"))
        os.makedirs(os.path.join(home, ".config"))
        for n in ("Downloads/office.conf", "Downloads/notes.txt", ".config/x.conf"):
            with open(os.path.join(home, n), "w") as fh:
                fh.write("[Interface]\n")
        with mock.patch.dict(os.environ, {"HOME": home}):
            r = netconn.network_vpn_import({"path": "/Downloads/office.conf"})
            self.assertEqual([c["name"] for c in r["imported"]], ["office2"])
            imp = [c for c in self.acts() if "import" in c][0]
            self.assertEqual(imp[:6], ["nmcli", "connection", "import", "type", "wireguard", "file"])
            for p in ("/Downloads/notes.txt", "/.config/x.conf", "/../etc/passwd"):
                with self.assertRaises(BackendError):
                    netconn.network_vpn_import({"path": p})

    def test_delete_vpn_only(self):
        netconn.network_vpn_delete({"uuid": V})
        self.assertEqual(self.acts()[0], ["nmcli", "connection", "delete", "uuid", V])
        with self.assertRaises(BackendError):
            netconn.network_vpn_delete({"uuid": W})


if __name__ == "__main__":
    unittest.main()
