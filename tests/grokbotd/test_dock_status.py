"""Dock status area: edge choice and items built from OS API results."""
import time
import unittest

import helpers  # noqa: F401  (sys.path)

import grokbot_status as st  # noqa: E402


def fake(results):
    return lambda m: results.get(m)


class StatusTests(unittest.TestCase):
    def test_status_edge(self):
        self.assertEqual(st.status_edge({"bottom": "icons"}), "bottom")
        self.assertEqual(st.status_edge({"bottom": "off", "left": "labels"}), "left")
        self.assertEqual(st.status_edge({"bottom": "icons", "status": "off"}), None)
        self.assertEqual(st.status_edge({"bottom": "icons", "top": "icons", "status": "top"}), "top")
        # A status edge whose dock is off shows nothing rather than a new dock.
        self.assertEqual(st.status_edge({"bottom": "icons", "status": "right"}), None)
        self.assertEqual(st.status_edge({}), None)

    def test_items_full(self):
        res = {
            "network.status": {"online": True, "default_route": {"interface": "wlp2s0"},
                               "interfaces": [{"name": "lo", "state": "unknown", "addresses": ["127.0.0.1/8"]},
                                              {"name": "wlp2s0", "state": "up", "wireless": True,
                                               "addresses": ["10.0.0.5/24"]}]},
            "audio.status": {"available": True, "output": {"volume_percent": 40, "muted": False}},
            "power.status": {"batteries": [{"capacity_percent": 78, "status": "Discharging"}], "on_ac": False},
        }
        items = st.items(fake(res), now=time.mktime((2026, 10, 21, 18, 5, 0, 0, 0, -1)))
        self.assertEqual([i["id"] for i in items], ["network", "volume", "battery", "clock"])
        by = {i["id"]: i for i in items}
        self.assertEqual(by["network"]["icon"], "network-wireless-signal-good-symbolic")
        self.assertEqual(by["volume"]["icon"], "audio-volume-medium-symbolic")
        self.assertEqual(by["battery"]["icon"], "battery-level-80-symbolic")
        self.assertEqual(by["battery"]["text"], "78%")
        self.assertEqual(by["clock"]["text"], "18:05")
        self.assertIsNone(by["clock"]["icon"])

    def test_items_desktop_vm(self):
        # No battery, wired, muted; daemon missing audio -> item dropped.
        res = {"network.status": {"online": True, "default_route": {"interface": "eth0"},
                                  "interfaces": [{"name": "eth0", "state": "up", "wireless": False,
                                                  "addresses": ["10.0.2.15/24"]}]},
               "power.status": {"batteries": [], "on_ac": True}}
        ids = [i["id"] for i in st.items(fake(res))]
        self.assertEqual(ids, ["network", "clock"])
        self.assertEqual(st.items(fake(res))[0]["icon"], "network-wired-symbolic")

    def test_offline_and_muted(self):
        res = {"network.status": {"online": False, "interfaces": []},
               "audio.status": {"available": True, "output": {"volume_percent": 50, "muted": True}}}
        by = {i["id"]: i for i in st.items(fake(res))}
        self.assertEqual(by["network"]["icon"], "network-offline-symbolic")
        self.assertEqual(by["volume"]["icon"], "audio-volume-muted-symbolic")

    def test_daemon_down(self):
        self.assertEqual([i["id"] for i in st.items(lambda m: None)], ["clock"])

    def test_battery_power_states(self):
        def battery(status, cap, on_ac):
            res = {"power.status": {"batteries": [{"capacity_percent": cap, "status": status}],
                                    "on_ac": on_ac}}
            return {i["id"]: i for i in st.items(fake(res))}["battery"]

        charging = battery("Charging", 42, True)
        self.assertEqual(charging["icon"], "battery-level-40-charging-symbolic")
        self.assertEqual(charging["text"], "충전 중")
        self.assertNotIn("전원 연결됨", charging["text"])

        charging_off_ac = battery("Charging", 42, False)
        self.assertEqual(charging_off_ac["icon"], "battery-level-40-charging-symbolic")
        self.assertEqual(charging_off_ac["text"], "충전 중")

        full = battery("Full", 100, True)
        self.assertEqual(full["icon"], "ac-adapter-symbolic")
        self.assertEqual(full["text"], "전원 연결됨 (가득 참)")

        held = battery("Not charging", 80, True)
        self.assertEqual(held["icon"], "ac-adapter-symbolic")
        self.assertEqual(held["text"], "전원 연결됨")

        discharging = battery("Discharging", 78, False)
        self.assertEqual(discharging["icon"], "battery-level-80-symbolic")
        self.assertEqual(discharging["text"], "78%")
        self.assertEqual(discharging["tooltip"], "배터리 / Battery 78%")

        # AC alone does not mean plugged-in or charging when the pack is discharging.
        discharging_ac = battery("Discharging", 78, True)
        self.assertEqual(discharging_ac["icon"], "battery-level-80-symbolic")
        self.assertEqual(discharging_ac["text"], "78%")


if __name__ == "__main__":
    unittest.main()
