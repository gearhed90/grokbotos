"""capture.status and grokbot-capture."""
import os
import subprocess
import unittest

import helpers

from grokbotd import capture  # noqa: E402


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.env = helpers.Env()
        self.dir = self.env.path("shots")
        os.environ["GROKBOT_SCREENSHOT_DIR"] = self.dir
        self.env.tool("grim", 'f="${@: -1}"; printf PNG >"$f"; echo "$*" >>"$HOME/grim.log"')
        self.env.tool("slurp", 'echo "10,20 300x200"')
        self.env.tool("wl-copy", 'cat >"$HOME/clip"; echo "$*" >"$HOME/clip.args"')
        self.env.tool("notify-send", 'echo "$*" >"$HOME/notify.log"')

    def tearDown(self):
        self.env.close()

    def run_capture(self, *args):
        return subprocess.run([os.path.join(helpers.BIN, "grokbot-capture"), *args],
                              capture_output=True, text=True, env=dict(os.environ))

    def test_full_saves_copies_notifies(self):
        r = self.run_capture("full")
        self.assertEqual(r.returncode, 0, r.stderr)
        path = r.stdout.strip()
        self.assertTrue(path.startswith(self.dir + "/screenshot-") and path.endswith(".png"))
        with open(os.path.join(self.env.root, "clip")) as f:
            self.assertEqual(f.read(), "PNG")
        with open(os.path.join(self.env.root, "clip.args")) as f:
            self.assertIn("image/png", f.read())
        with open(os.path.join(self.env.root, "notify.log")) as f:
            self.assertIn("Screenshot saved", f.read())

    def test_region_uses_slurp_geometry(self):
        self.assertEqual(self.run_capture("region").returncode, 0)
        with open(os.path.join(self.env.root, "grim.log")) as f:
            self.assertIn("-g 10,20 300x200", f.read())

    def test_status(self):
        self.assertEqual(capture.capture_status({})["count"], 0)
        self.run_capture("full")
        s = capture.capture_status({"limit": 5})
        self.assertEqual((s["dir"], s["count"]), (self.dir, 1))
        self.assertEqual(s["recent"][0]["size_bytes"], 3)
        self.assertTrue(all(s["tools"].values()))

    def test_bad_mode(self):
        self.assertEqual(self.run_capture("video").returncode, 2)


if __name__ == "__main__":
    unittest.main()
