"""files.* with volume: rooted at an open removable drive under /run/media/<user>/ only."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "system_files", "usr", "lib", "grokbot"))
from grokbotd import files, storage  # noqa: E402
from grokbotd.backends import BackendError  # noqa: E402

M = files.METHODS


class VolumeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.base = os.path.join(self.tmp, "media")
        self.stick = os.path.join(self.base, "PHOTOS")
        self.home = os.path.join(self.tmp, "home")
        for d in (self.stick, self.home):
            os.makedirs(d)
        with open(os.path.join(self.stick, "a.txt"), "w") as fh:
            fh.write("hi")
        os.makedirs(os.path.join(self.stick, ".secret"))
        os.symlink(self.home, os.path.join(self.stick, "esc"))
        self.vols = {"sdb1": {"id": "sdb1", "mounted": True, "mount_points": [self.stick]},
                     "sdc1": {"id": "sdc1", "mounted": False, "mount_points": []},
                     "sdd1": {"id": "sdd1", "mounted": True, "mount_points": [self.home]}}
        self.p = [mock.patch.dict(os.environ, {"GROKBOT_MEDIA_BASE": self.base, "HOME": self.home}),
                  mock.patch.object(storage, "_find", side_effect=self.find)]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()

    def find(self, vid):
        if vid not in self.vols:
            raise BackendError("no such volume")
        return self.vols[vid]

    def test_list_on_drive(self):
        r = M["files.list"]({"path": "/", "volume": "sdb1"})
        names = sorted(e["name"] for e in r["entries"])
        self.assertIn("a.txt", names)
        self.assertNotIn(".secret", names)
        self.assertEqual(r["volume"], "sdb1")
        self.assertEqual(M["files.read"]({"path": "/a.txt", "volume": "sdb1"})["data"], "hi")

    def test_root_resets_to_home(self):
        M["files.list"]({"path": "/", "volume": "sdb1"})
        self.assertEqual(files.home(), os.path.realpath(self.home))

    def test_symlink_escape_refused(self):
        with self.assertRaises(BackendError):
            M["files.list"]({"path": "/esc", "volume": "sdb1"})
        with self.assertRaises(BackendError):
            M["files.read"]({"path": "/../home", "volume": "sdb1"})

    def test_hidden_refused(self):
        with self.assertRaises(BackendError):
            M["files.list"]({"path": "/.secret", "volume": "sdb1"})

    def test_unmounted_or_outside_media_refused(self):
        for v in ("sdc1", "sdd1", "zz9"):
            with self.assertRaises(BackendError):
                M["files.list"]({"path": "/", "volume": v})

    def test_write_and_trash_on_drive(self):
        M["files.write"]({"path": "/b.txt", "data": "x", "volume": "sdb1"})
        self.assertTrue(os.path.exists(os.path.join(self.stick, "b.txt")))
        M["files.trash"]({"path": "/b.txt", "volume": "sdb1"})
        self.assertTrue(os.path.exists(os.path.join(self.stick, ".Trash-%d" % os.getuid(), "files", "b.txt")))


if __name__ == "__main__":
    unittest.main()
