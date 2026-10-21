"""audio.status, display.brightness and the key scripts."""
import os
import subprocess
import unittest

import helpers

from grokbotd import media  # noqa: E402

FAKE_WPCTL = '''
state="$HOME/wpctl.log"
case $1 in
  get-volume) if [[ $2 == *SINK* ]]; then echo "Volume: 0.40"; else echo "Volume: 0.75 [MUTED]"; fi ;;
  *) echo "$*" >>"$state" ;;
esac
'''


class MediaTests(unittest.TestCase):
    def setUp(self):
        self.env = helpers.Env()

    def tearDown(self):
        self.env.close()

    def test_audio_status(self):
        self.env.tool("wpctl", FAKE_WPCTL)
        self.assertEqual(media.audio_status({}), {
            "available": True,
            "output": {"volume_percent": 40, "muted": False},
            "input": {"volume_percent": 75, "muted": True}})

    def test_audio_status_without_pipewire(self):
        os.environ["PATH"] = self.env.bin
        self.assertEqual(media.audio_status({}), {"available": False, "output": None, "input": None})

    def test_brightness(self):
        self.assertEqual(media.display_brightness({}), {"available": False, "devices": []})
        self.env.write("sys/class/backlight/intel_backlight/brightness", "300\n")
        self.env.write("sys/class/backlight/intel_backlight/max_brightness", "1200\n")
        d = media.display_brightness({})
        self.assertEqual(d["devices"], [{"name": "intel_backlight", "brightness": 300,
                                         "max_brightness": 1200, "percent": 25}])

    def test_volume_script(self):
        self.env.tool("wpctl", FAKE_WPCTL)
        exe = os.path.join(helpers.BIN, "grokbot-volume")
        env = dict(os.environ)
        out = subprocess.run([exe, "get"], capture_output=True, text=True, env=env, check=True)
        self.assertEqual(out.stdout.strip(), "40")
        # up unmutes and caps at 100%; the OSD path is absent here and must not fail.
        r = subprocess.run(["bash", "-c", "sed 's#/usr/local/bin/grokbot-osd#true#' %s | bash -s up" % exe],
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(self.env.root, "wpctl.log")) as f:
            log = f.read()
        self.assertIn("set-mute @DEFAULT_AUDIO_SINK@ 0", log)
        self.assertIn("set-volume -l 1.0 @DEFAULT_AUDIO_SINK@ 5%+", log)

    def test_osd_rejects_garbage_and_never_blocks(self):
        exe = os.path.join(helpers.BIN, "grokbot-osd")
        env = dict(os.environ)
        self.assertEqual(subprocess.run([exe, "abc"], capture_output=True, env=env).returncode, 2)
        self.assertEqual(subprocess.run([exe, "150"], capture_output=True, env=env, timeout=5).returncode, 0)


if __name__ == "__main__":
    unittest.main()
