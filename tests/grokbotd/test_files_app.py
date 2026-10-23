"""Files web app: drive list follows hotplug; an opened drive explains the
files permission it needs instead of showing the home-folder card."""
import os
import re
import unittest

import helpers

APP = os.path.join(helpers.SF, "usr/share/grokbot/webapps/files/app.js")


class FilesAppTest(unittest.TestCase):
    def setUp(self):
        with open(APP, encoding="utf-8") as f:
            self.src = f.read()

    def test_polls_drives(self):
        self.assertIn("setInterval(pollDrives", self.src)
        self.assertIn('addEventListener("visibilitychange", pollDrives)', self.src)
        self.assertRegex(self.src, r"async function pollDrives\(\)[\s\S]*document\.hidden")

    def test_drive_permission_message_both_languages(self):
        self.assertEqual(len(re.findall(r"\bneedreadvol:", self.src)), 2)
        self.assertIn('vol ? t("needreadvol", vol.label) : t("needread")', self.src)
        self.assertIn('go(vol ? "/" : cwd)', self.src)


if __name__ == "__main__":
    unittest.main()
