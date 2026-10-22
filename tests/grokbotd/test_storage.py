"""storage.*: removable volumes from UDisks2 JSON; system disk never listed."""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "system_files", "usr", "lib", "grokbot"))
from grokbotd import storage  # noqa: E402
from grokbotd.backends import BackendError  # noqa: E402

B = "/org/freedesktop/UDisks2/block_devices/"
D = "/org/freedesktop/UDisks2/drives/"


def ay(s):
    return {"type": "ay", "data": list(s.encode()) + [0]}


def t(typ, v):
    return {"type": typ, "data": v}


def managed(mounted=False):
    return {"type": "a{oa{sa{sv}}}", "data": [{
        D + "QEMU_HARDDISK": {"org.freedesktop.UDisks2.Drive": {"Removable": t("b", False), "ConnectionBus": t("s", "")}},
        D + "SanDisk_Ultra": {"org.freedesktop.UDisks2.Drive": {"Removable": t("b", True), "Ejectable": t("b", True),
                                                                 "ConnectionBus": t("s", "usb"), "Vendor": t("s", "SanDisk"),
                                                                 "Model": t("s", "Ultra")}},
        B + "vda3": {"org.freedesktop.UDisks2.Block": {"Device": ay("/dev/vda3"), "IdUsage": t("s", "filesystem"),
                                                       "IdType": t("s", "xfs"), "Drive": t("o", D + "QEMU_HARDDISK"),
                                                       "HintSystem": t("b", True)},
                     "org.freedesktop.UDisks2.Filesystem": {"MountPoints": t("aay", [list(b"/sysroot\0")])}},
        B + "sdb1": {"org.freedesktop.UDisks2.Block": {"Device": ay("/dev/sdb1"), "IdUsage": t("s", "filesystem"),
                                                       "IdType": t("s", "vfat"), "IdLabel": t("s", "PHOTOS"),
                                                       "Size": t("t", 16000000000), "Drive": t("o", D + "SanDisk_Ultra"),
                                                       "HintSystem": t("b", False)},
                     "org.freedesktop.UDisks2.Filesystem": {
                         "MountPoints": t("aay", [list(b"/run/media/grokbot/PHOTOS\0")] if mounted else [])}},
        B + "sdb": {"org.freedesktop.UDisks2.Block": {"Device": ay("/dev/sdb"), "IdUsage": t("s", ""),
                                                      "Drive": t("o", D + "SanDisk_Ultra")}},
    }]}


class StorageTest(unittest.TestCase):
    def setUp(self):
        self.calls, self.mounted = [], False

        def run(cmd, timeout=30):
            if "GetManagedObjects" in cmd:
                return json.dumps(managed(self.mounted))
            self.calls.append(cmd)
            if cmd[-3] == "Mount":
                self.mounted = True
            if cmd[-3] == "Unmount":
                self.mounted = False
            return ""
        self.p = mock.patch.object(storage, "_run", run)
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_list_only_removable(self):
        r = storage.storage_list({})
        self.assertTrue(r["available"])
        self.assertEqual([v["id"] for v in r["volumes"]], ["sdb1"])
        v = r["volumes"][0]
        self.assertEqual((v["name"], v["fs"], v["device"], v["drive"]), ("PHOTOS", "vfat", "/dev/sdb1", "SanDisk Ultra"))
        self.assertFalse(v["mounted"])

    def test_mount_unmount_eject(self):
        v = storage.storage_mount({"id": "sdb1"})
        self.assertEqual(self.calls[0][3:], ["org.freedesktop.UDisks2", B + "sdb1", "org.freedesktop.UDisks2.Filesystem",
                                              "Mount", "a{sv}", "0"])
        self.assertEqual(v["mount_points"], ["/run/media/grokbot/PHOTOS"])
        r = storage.storage_unmount({"id": "sdb1", "eject": True})
        self.assertEqual([c[-3] for c in self.calls], ["Mount", "Unmount", "Eject"])
        self.assertEqual(self.calls[-1][4], D + "SanDisk_Ultra")
        self.assertTrue(r["ejected"])

    def test_refuses_system_and_bad_ids(self):
        for bad in ("vda3", "sdb", "../x", "sdb1;x", "", "SDB1"):
            with self.assertRaises(BackendError):
                storage.storage_mount({"id": bad})
        self.assertEqual(self.calls, [])

    def test_unavailable(self):
        with mock.patch.object(storage, "_run", mock.Mock(side_effect=BackendError("x"))):
            self.assertEqual(storage.storage_list({}), {"available": False, "volumes": []})
            with self.assertRaises(BackendError):
                storage.storage_mount({"id": "sdb1"})

    def test_friendly(self):
        self.assertIn("in use", storage._friendly("org.freedesktop.UDisks2.Error.DeviceBusy: target is busy"))


if __name__ == "__main__":
    unittest.main()
