"""notifications.list and grokbot-notify-dnd."""
import json
import os
import subprocess
import unittest

import helpers

from grokbotd import notify  # noqa: E402

OLD = {"type": "aa{sv}", "data": [[
    {"app-name": {"type": "s", "data": "Grok Bot"}, "summary": {"type": "s", "data": "Done"},
     "body": {"type": "s", "data": "secret body"}, "id": {"type": "u", "data": 3},
     "urgency": {"type": "y", "data": 1}}]]}
NEW = [{"app_name": "Firefox", "summary": "Download", "body": "x", "id": 7, "urgency": 2}]


class NotifyTests(unittest.TestCase):
    def setUp(self):
        self.env = helpers.Env()

    def tearDown(self):
        self.env.close()

    def fake_mako(self, listing, modes="default"):
        self.env.proc(500, "mako")
        self.env.write("list.json", json.dumps(listing))
        self.env.tool("makoctl", '''
case $1 in
  mode) if [[ $# -gt 1 ]]; then echo "$*" >>"$HOME/modes.log"; fi; printf '%%s\\n' %s ;;
  list|history) [[ ${2:-} == -j || %d == 1 ]] && cat "$HOME/list.json" ;;
esac''' % (modes, 1 if isinstance(listing, dict) else 0))

    def test_old_makoctl_format_and_no_body(self):
        self.fake_mako(OLD)
        r = notify.notifications_list({})
        self.assertEqual(r, {"daemon_running": True, "dnd": False, "notifications": [
            {"id": 3, "app": "Grok Bot", "summary": "Done", "urgency": "normal"}]})
        self.assertNotIn("secret", json.dumps(r))

    def test_new_format_dnd_history(self):
        self.fake_mako(NEW, modes="'default do-not-disturb'")
        r = notify.notifications_list({"include_history": True})
        self.assertTrue(r["dnd"])
        self.assertEqual(r["notifications"][0]["urgency"], "critical")
        self.assertEqual(r["history"][0]["app"], "Firefox")

    def test_no_daemon(self):
        self.assertEqual(notify.notifications_list({}),
                         {"daemon_running": False, "dnd": False, "notifications": []})

    def test_dnd_script(self):
        self.fake_mako(NEW)
        self.env.tool("notify-send", "true")
        exe = os.path.join(helpers.BIN, "grokbot-notify-dnd")
        env = dict(os.environ)
        self.assertEqual(subprocess.run([exe, "status"], capture_output=True, text=True,
                                        env=env).stdout.strip(), "off")
        subprocess.run([exe, "toggle"], check=True, capture_output=True, env=env)
        with open(os.path.join(self.env.root, "modes.log")) as f:
            self.assertIn("mode -t do-not-disturb", f.read())
        self.assertEqual(subprocess.run([exe, "bogus"], capture_output=True, env=env).returncode, 2)


if __name__ == "__main__":
    unittest.main()
