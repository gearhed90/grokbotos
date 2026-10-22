"""power.profile.*: power-profiles D-Bus API through busctl."""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "system_files", "usr", "lib", "grokbot"))
from grokbotd import powermode as pm  # noqa: E402
from grokbotd.backends import BackendError  # noqa: E402


def answer(active="balanced", offered=("power-saver", "balanced")):
    profs = [{"Profile": {"type": "s", "data": p}, "Driver": {"type": "s", "data": "tuned"}} for p in offered]
    return "\n".join(json.dumps(x) for x in ({"type": "s", "data": active}, {"type": "aa{sv}", "data": profs},
                                             {"type": "s", "data": ""})) + "\n"


class PowerModeTest(unittest.TestCase):
    def setUp(self):
        self.calls, self.active = [], "balanced"

        def run(cmd, timeout=5):
            if "get-property" in cmd:
                return answer(self.active)
            self.calls.append(cmd)
            self.active = cmd[-1]
            return ""
        self.p = mock.patch.object(pm, "_run", run)
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_status(self):
        r = pm.profile_status({})
        self.assertEqual(r, {"available": True, "active": "balanced", "profiles": ["power-saver", "balanced"],
                             "degraded": ""})

    def test_set(self):
        r = pm.profile_set({"profile": "power-saver"})
        self.assertEqual(self.calls[0][-6:], ["org.freedesktop.UPower.PowerProfiles", "/org/freedesktop/UPower/PowerProfiles",
                                              "org.freedesktop.UPower.PowerProfiles", "ActiveProfile", "s", "power-saver"][-6:])
        self.assertEqual(r["active"], "power-saver")
        with self.assertRaises(BackendError):
            pm.profile_set({"profile": "performance"})  # not offered (no platform driver)
        with self.assertRaises(BackendError):
            pm.profile_set({"profile": "turbo"})

    def test_unavailable(self):
        with mock.patch.object(pm, "_run", mock.Mock(side_effect=BackendError("x"))):
            self.assertFalse(pm.profile_status({})["available"])


if __name__ == "__main__":
    unittest.main()
