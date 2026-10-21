"""input.status (fcitx5)."""
import os
import unittest

import helpers

from grokbotd import inputmethod  # noqa: E402


class InputTests(unittest.TestCase):
    def setUp(self):
        self.env = helpers.Env()
        etc = os.path.join(helpers.SF, "etc", "xdg", "fcitx5")
        os.environ["GROKBOT_FCITX_SYS_PROFILE"] = os.path.join(etc, "profile")
        os.environ["GROKBOT_FCITX_SYS_CONFIG"] = os.path.join(etc, "config")
        os.environ["XMODIFIERS"] = "@im=fcitx"

    def tearDown(self):
        self.env.close()

    def test_defaults_not_running(self):
        s = inputmethod.input_status({})
        self.assertFalse(s["running"])
        self.assertEqual(s["input_methods"], ["keyboard-us", "hangul"])
        self.assertEqual(s["trigger_keys"], ["Hangul", "Shift+space", "Alt_R"])
        self.assertEqual(s["xmodifiers"], "@im=fcitx")
        self.assertIsNone(s["current"])

    def test_running_hangul_active(self):
        self.env.proc(700, "fcitx5")
        self.env.tool("fcitx5-remote", 'if [[ ${1:-} == -n ]]; then echo hangul; else echo 2; fi')
        s = inputmethod.input_status({})
        self.assertEqual((s["running"], s["current"], s["active"]), (True, "hangul", True))

    def test_user_profile_overrides(self):
        self.env.write("cfg/fcitx5/profile", "[Groups/0/Items/0]\nName=keyboard-kr\n")
        self.assertEqual(inputmethod.input_status({})["input_methods"], ["keyboard-kr"])


if __name__ == "__main__":
    unittest.main()
