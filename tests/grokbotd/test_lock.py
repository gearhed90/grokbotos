"""lock.status backend and the grokbot-idle / grokbot-lock-setup scripts."""
import os
import subprocess
import unittest

import helpers

from grokbotd import lock  # noqa: E402


class LockStatusTests(unittest.TestCase):
    def setUp(self):
        self.env = helpers.Env()
        os.environ["GROKBOT_LOCK_STATE_DIR"] = self.env.path("lockstate")
        os.environ["GROKBOT_IDLE_SYS_CONF"] = os.path.join(helpers.SF, "etc", "grokbot", "idle.conf")

    def tearDown(self):
        self.env.close()

    def test_defaults_no_pin(self):
        s = lock.lock_status({})
        self.assertEqual(s, {"pin_set": False, "setup_skipped": False, "locked": False,
                             "idle_running": False, "screen_off_s": 300, "lock_s": 600})

    def test_pin_locked_and_user_override(self):
        import pwd
        user = pwd.getpwuid(os.getuid()).pw_name
        self.env.write("lockstate/" + user, "2026-10-21T00:00:00Z\n")
        self.env.proc(4242, "swaylock")
        self.env.proc(4243, "swayidle")
        self.env.write("cfg/grokbot/idle.conf", "[idle]\nlock = 120\n")
        s = lock.lock_status({})
        self.assertTrue(s["pin_set"] and s["locked"] and s["idle_running"])
        self.assertEqual((s["screen_off_s"], s["lock_s"]), (300, 120))

    def test_idle_print_uses_config(self):
        self.env.write("cfg/grokbot/idle.conf", "[idle]\nscreen_off = 0\nlock = 90\n")
        out = subprocess.run([os.path.join(helpers.BIN, "grokbot-idle"), "--print"],
                             capture_output=True, text=True, check=True,
                             env=dict(os.environ)).stdout
        self.assertNotIn("power\\ off", out)
        self.assertIn("timeout 90 /usr/local/bin/grokbot-lock", out)
        self.assertIn("before-sleep /usr/local/bin/grokbot-lock", out)

    def test_setup_status_and_skip(self):
        exe = os.path.join(helpers.BIN, "grokbot-lock-setup")
        env = dict(os.environ)
        self.assertEqual(subprocess.run([exe, "--status"], capture_output=True, text=True,
                                        env=env).stdout.strip(), "unset")
        subprocess.run([exe, "--skip"], check=True, env=env)
        self.assertTrue(lock.lock_status({})["setup_skipped"])

    def test_no_pin_in_repo(self):
        # The PIN must never be hard-coded: the helper only reads stdin.
        with open(os.path.join(helpers.LIB, "lock-setpin.sh")) as f:
            text = f.read()
        self.assertIn("read -r pin", text)
        self.assertNotRegex(text, r"chpasswd <<<|passwd [a-z]+ [0-9]{4}")


if __name__ == "__main__":
    unittest.main()
