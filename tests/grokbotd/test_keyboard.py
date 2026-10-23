"""keyboard.layout.*: allow-listed layouts only; sway + fcitx5 profile updated, hangul kept."""
import configparser
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "system_files", "usr", "lib", "grokbot"))
from grokbotd import keyboard, procs, sway  # noqa: E402
from grokbotd.backends import BackendError  # noqa: E402


class KeyboardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sent = []

        def call(t, payload=b""):
            if t == sway.RUN_COMMAND:
                self.sent.append(payload.decode())
                return [{"success": True}, {"success": True}]
            return [{"type": "pointer"}, {"type": "keyboard", "xkb_active_layout_name": "English (US)",
                                          "xkb_layout_names": ["English (US)"]}]
        self.p = [mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": self.tmp,
                                               "GROKBOT_FCITX_SYS_PROFILE": os.path.join(
                                                   os.path.dirname(__file__), "..", "..", "system_files",
                                                   "etc", "xdg", "fcitx5", "profile")}),
                  mock.patch.object(sway, "call", call),
                  mock.patch.object(procs, "running", lambda n, uid=None: False)]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()

    def profile(self):
        cp = configparser.ConfigParser(interpolation=None)
        cp.optionxform = str
        cp.read(os.path.join(self.tmp, "fcitx5", "profile"))
        return cp

    def test_status_default(self):
        r = keyboard.keyboard_layout_status({})
        self.assertEqual(r["layout"], "us")
        self.assertTrue(r["korean_input"])
        self.assertEqual(r["active_name"], "English (US)")
        self.assertIn("kr", [x["id"] for x in r["available"]])

    def test_set_dvorak_keeps_hangul(self):
        r = keyboard.keyboard_layout_set({"layout": "us-dvorak"})
        self.assertEqual(self.sent, ['input type:keyboard xkb_layout "us"; input type:keyboard xkb_variant "dvorak"'])
        cp = self.profile()
        self.assertEqual(cp["Groups/0"]["Default Layout"], "us-dvorak")
        self.assertEqual(cp["Groups/0/Items/0"]["Name"], "keyboard-us-dvorak")
        self.assertEqual(cp["Groups/0/Items/1"]["Name"], "hangul")
        self.assertEqual(r["layout"], "us-dvorak")
        self.assertTrue(r["korean_input"])
        with open(keyboard.conf_path()) as fh:
            self.assertIn('xkb_variant "dvorak"', fh.read())

    def test_set_twice_no_duplicates(self):
        keyboard.keyboard_layout_set({"layout": "kr"})
        keyboard.keyboard_layout_set({"layout": "de"})
        names = [self.profile()[s]["Name"] for s in self.profile().sections() if s.startswith("Groups/0/Items/")]
        self.assertEqual(names, ["keyboard-de", "hangul"])
        self.assertEqual(keyboard.saved(), "de")

    def test_unknown_layout_refused(self):
        for bad in ("zz", 'us"; exec rm', "us-foo"):
            with self.assertRaises(BackendError):
                keyboard.keyboard_layout_set({"layout": bad})
        self.assertEqual(self.sent, [])

    def test_sway_refusal(self):
        with mock.patch.object(sway, "call", lambda t, p=b"": [{"success": False, "error": "x"}]):
            with self.assertRaises(BackendError):
                keyboard.keyboard_layout_set({"layout": "gb"})
        self.assertFalse(os.path.exists(keyboard.conf_path()))


if __name__ == "__main__":
    unittest.main()
