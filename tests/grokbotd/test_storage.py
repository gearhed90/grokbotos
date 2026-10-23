"""storage.*: removable volumes from UDisks2 JSON; system disk never listed."""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "system_files", "usr", "lib", "grokbot"))
sys.path.insert(0, os.path.dirname(__file__))
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


def managed_luks(unlocked=False, mounted=False, fs="exfat"):
    d = {
        D + "Kingston": {"org.freedesktop.UDisks2.Drive": {"Removable": t("b", True), "Ejectable": t("b", True),
                                                            "ConnectionBus": t("s", "usb"), "Vendor": t("s", "Kingston"),
                                                            "Model": t("s", "DT")}},
        B + "sdc1": {"org.freedesktop.UDisks2.Block": {"Device": ay("/dev/sdc1"), "IdUsage": t("s", "crypto"),
                                                       "IdType": t("s", "crypto_LUKS"), "IdLabel": t("s", "SECRET"),
                                                       "Drive": t("o", D + "Kingston"), "CryptoBackingDevice": t("o", "/")},
                     "org.freedesktop.UDisks2.Encrypted": {
                         "CleartextDevice": t("o", B + "dm_2d0" if unlocked else "/")}},
    }
    if unlocked:
        d[B + "dm_2d0"] = {"org.freedesktop.UDisks2.Block": {"Device": ay("/dev/dm-0"), "IdUsage": t("s", "filesystem"),
                                                             "IdType": t("s", fs), "IdLabel": t("s", ""),
                                                             "Drive": t("o", "/"), "CryptoBackingDevice": t("o", B + "sdc1")},
                           "org.freedesktop.UDisks2.Filesystem": {
                               "MountPoints": t("aay", [list(b"/run/media/grokbot/x\0")] if mounted else [])}}
    return {"type": "a{oa{sa{sv}}}", "data": [d]}


class LuksTest(unittest.TestCase):
    def setUp(self):
        self.calls, self.unlocked, self.mounted = [], False, False

        def run(cmd, timeout=30):
            if "GetManagedObjects" in cmd:
                return json.dumps(managed_luks(self.unlocked, self.mounted))
            self.calls.append(cmd)
            if cmd[-3] == "Mount":
                self.mounted = True
            if cmd[-3] == "Unmount":
                self.mounted = False
            if cmd[-3] == "Lock":
                self.unlocked = False
            return ""
        self.p = mock.patch.object(storage, "_run", run)
        self.p.start()
        self.unlock_args = []

        def unlock(path, pw):
            self.unlock_args.append((path, pw))
            if pw != "correct horse":
                raise BackendError("storage: wrong passphrase")
            self.unlocked = True
            return B + "dm_2d0"
        self.p2 = mock.patch.object(storage, "_unlock_dbus", unlock)
        self.p2.start()
        self.ctx = {"principal": "local:uid=1000", "client": None}

    def tearDown(self):
        mock.patch.stopall()

    def prompt(self, ans):
        return mock.patch.object(storage, "_secret_prompt", lambda ctx, v: ans)

    def test_list_locked(self):
        v = storage.storage_list({})["volumes"]
        self.assertEqual([(x["id"], x["encrypted"], x["locked"], x["fs"]) for x in v],
                         [("sdc1", True, True, "crypto_LUKS")])
        with self.assertRaises(BackendError):
            storage.storage_mount({"id": "sdc1"})

    def test_unlock_mount_lock(self):
        with self.prompt(("once", "user", "correct horse")):
            v = storage.storage_unlock({"id": "sdc1"}, self.ctx)
        self.assertEqual(self.unlock_args, [(B + "sdc1", "correct horse")])
        self.assertEqual((v["id"], v["backing"], v["mounted"], v["label"], v["fs"]), ("dm_2d0", "sdc1", True, "SECRET", "exfat"))
        # never on a command line
        self.assertFalse(any("correct horse" in " ".join(c) for c in self.calls))
        lst = storage.storage_list({})["volumes"]
        self.assertEqual([x["id"] for x in lst], ["dm_2d0"])
        r = storage.storage_lock({"id": "dm_2d0"})
        self.assertEqual(r, {"id": "sdc1", "locked": True})
        self.assertEqual([c[-3] for c in self.calls], ["Mount", "Unmount", "Lock"])
        self.assertEqual(self.calls[-1][4:6], [B + "sdc1", "org.freedesktop.UDisks2.Encrypted"])

    def test_unlock_cancel_and_wrong(self):
        from grokbotd.webapps import Denied
        with self.prompt(("deny", "user", None)), self.assertRaises(Denied):
            storage.storage_unlock({"id": "sdc1"}, self.ctx)
        self.assertEqual(self.unlock_args, [])
        with self.prompt(("once", "user", "nope")), self.assertRaises(BackendError) as e:
            storage.storage_unlock({"id": "sdc1"}, self.ctx)
        self.assertNotIn("nope", str(e.exception))

    def test_eject_locks(self):
        self.unlocked = self.mounted = True
        r = storage.storage_unmount({"id": "dm_2d0", "eject": True})
        self.assertEqual([c[-3] for c in self.calls], ["Unmount", "Lock", "Eject"])
        self.assertTrue(r["ejected"] and r["locked"])


class UnlockDispatchTest(unittest.TestCase):
    """rpc: storage.unlock skips the generic prompt (the passphrase prompt is
    the consent), deny still denies, and the audit log never has a secret."""

    def setUp(self):
        import helpers
        from grokbotd import rpc, schema
        self.env = helpers.Env()
        os.environ["GROKBOT_API_SYS_PERMISSIONS"] = self.env.write("sys.json", json.dumps({"local": {"storage": "ask"}}))
        os.environ["GROKBOT_API_SCHEMA"] = os.path.join(helpers.SF, "usr/share/grokbot/api/os-api.schema.json")
        self.rpc, self.disp = rpc, rpc.Dispatcher(schema.load())
        self.generic = mock.patch("grokbotd.consent.prompt", side_effect=AssertionError("generic prompt shown"))
        self.generic.start()
        self.unlock = mock.patch.dict(rpc.CTX_METHODS, {"storage.unlock": lambda p, c: {"id": "dm_2d0", "pw_seen": "hidden"}})
        self.unlock.start()

    def tearDown(self):
        mock.patch.stopall()
        self.env.close()

    def call(self):
        return self.disp.handle({"jsonrpc": "2.0", "id": 1, "method": "storage.unlock", "params": {"id": "sdc1"}},
                                "local:uid=1000:exe=/usr/bin/x", "unix")

    def audit(self):
        with open(os.path.join(self.env.root, "state", "grokbot", "audit.jsonl")) as f:
            return [json.loads(x) for x in f if x.strip()]

    def test_ask_uses_secret_prompt_only(self):
        r = self.call()
        self.assertEqual(r["result"]["id"], "dm_2d0")
        a = self.audit()[-1]
        self.assertEqual((a["decision"], a.get("consent")), ("allow", "secret_prompt"))
        self.assertEqual(a["params"], {"id": "sdc1"})

    def test_deny_mode(self):
        from grokbotd import perms
        perms.set_mode("local:uid=1000:exe=/usr/bin/x", "storage", "deny", by="test")
        r = self.call()
        self.assertEqual(r["error"]["code"], self.rpc.PERMISSION_DENIED)


class SecretPromptTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.cmd = os.path.join(self.tmp.name, "p")
        self.seen = os.path.join(self.tmp.name, "seen")
        os.environ["GROKBOT_CONSENT_CMD"] = self.cmd

    def tearDown(self):
        os.environ.pop("GROKBOT_CONSENT_CMD", None)
        self.tmp.cleanup()

    def fake(self, out):
        with open(self.cmd, "w") as f:
            f.write("#!/bin/bash\ncat >%s\necho '%s'\n" % (self.seen, out))
        os.chmod(self.cmd, 0o755)

    def test_answers(self):
        from grokbotd import consent
        self.fake('{"answer": "once", "secret": "pw 1"}')
        self.assertEqual(consent.secret_prompt("local:x", None, "storage", "storage.unlock", ["a", "b"], {}, None),
                         ("once", "user", "pw 1"))
        with open(self.seen) as f:
            req = json.load(f)
        self.assertTrue(req["secret"])
        self.assertFalse(req["allow_always"] or req["allow_session"])
        self.fake('{"answer": "deny", "secret": null}')
        self.assertEqual(consent.secret_prompt("local:x", None, "storage", "storage.unlock", ["a", "b"], {}, None)[0], "deny")
        self.fake('once')
        self.assertEqual(consent.secret_prompt("local:x", None, "storage", "storage.unlock", ["a", "b"], {}, None),
                         ("deny", "bad_answer", None))


if __name__ == "__main__":
    unittest.main()
