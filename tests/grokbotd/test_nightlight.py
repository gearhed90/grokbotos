"""Night light: config validation, persistence, unit start/stop."""
import json
import os
import tempfile
import unittest
from unittest import mock

import helpers  # noqa: F401  (sys.path)

from grokbotd import nightlight  # noqa: E402
from grokbotd.backends import BackendError  # noqa: E402


class NightlightTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.calls = []
        p = [mock.patch.object(nightlight.paths, "config_home", return_value=self.tmp.name),
             mock.patch.object(nightlight.shutil, "which", return_value="/usr/bin/x"),
             mock.patch.object(nightlight, "_systemctl", side_effect=self._sc)]
        for x in p:
            x.start()
            self.addCleanup(x.stop)
        self.active = False

    def _sc(self, *args):
        self.calls.append(args)
        if args[0] == "restart":
            self.active = True
        if args[0] == "stop":
            self.active = False
        if args[0] == "is-active":
            return (0 if self.active else 3), ""
        return 0, ""

    def test_defaults(self):
        s = nightlight.status()
        self.assertFalse(s["enabled"])
        self.assertEqual(s["temperature"], 4000)
        self.assertTrue(s["available"])

    def test_enable_saves_and_restarts(self):
        s = nightlight.set_nightlight({"enabled": True, "temperature": 3200})
        self.assertTrue(s["enabled"] and s["running"])
        self.assertIn(("restart", nightlight.UNIT), self.calls)
        with open(nightlight.conf_path()) as f:
            self.assertEqual(json.load(f)["temperature"], 3200)
        s = nightlight.set_nightlight({"enabled": False})
        self.assertFalse(s["running"])
        self.assertEqual(s["temperature"], 3200)

    def test_validation(self):
        for bad in ({"temperature": 1000}, {"schedule": "sometimes"}, {"from": "25:00"},
                    {"schedule": "custom", "from": "07:00", "to": "07:00"}):
            with self.assertRaises(BackendError):
                nightlight.set_nightlight(bad)
        self.assertFalse(os.path.exists(nightlight.conf_path()))

    def test_missing_gammastep(self):
        with mock.patch.object(nightlight.shutil, "which", return_value=None):
            self.assertFalse(nightlight.status()["available"])
            with self.assertRaises(BackendError):
                nightlight.set_nightlight({"enabled": True})


if __name__ == "__main__":
    unittest.main()
