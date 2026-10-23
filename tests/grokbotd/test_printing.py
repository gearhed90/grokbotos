"""printers.* / print.*: CUPS through fake lpstat/lp/lpoptions/cancel on PATH."""
import os
import stat
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "system_files", "usr", "lib", "grokbot"))
from grokbotd import printing  # noqa: E402
from grokbotd.backends import BackendError  # noqa: E402

M = printing.METHODS

LPSTAT = r'''#!/bin/sh
case "$*" in
  "-p -v") printf 'printer Office is idle.  enabled since x\nprinter Old disabled since y -\n\tPaused\ndevice for Office: ipp://10.0.0.5/ipp/print\ndevice for Old: usb://HP/LaserJet\n';;
  "-d") printf 'system default destination: Office\n';;
  "-e") printf 'Office\nHall_Printer\n';;
  "-o") printf 'Office-12               me             2048   Fri 23 Oct\n';;
esac
'''


class PrintingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.bin = os.path.join(self.tmp, "bin")
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.bin)
        os.makedirs(self.home)
        self.log = os.path.join(self.tmp, "log")
        self._tool("lpstat", LPSTAT)
        for t in ("lp", "lpoptions", "cancel"):
            self._tool(t, '#!/bin/sh\necho "%s $*" >> %s\n[ %s = lp ] && echo "request id is Office-13 (1 file(s))"\nexit 0\n' % (t, self.log, t))
        with open(os.path.join(self.home, "doc.pdf"), "w") as fh:
            fh.write("%PDF")
        p = mock.patch.dict(os.environ, {"PATH": self.bin + ":/usr/bin:/bin", "HOME": self.home})
        p.start()
        self.addCleanup(p.stop)

    def _tool(self, name, body):
        path = os.path.join(self.bin, name)
        with open(path, "w") as fh:
            fh.write(body)
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as fh:
            return fh.read().splitlines()

    def test_list(self):
        r = M["printers.list"]({})
        self.assertTrue(r["available"])
        by = {p["name"]: p for p in r["printers"]}
        self.assertEqual(set(by), {"Office", "Old", "Hall_Printer"})
        self.assertTrue(by["Office"]["default"] and by["Office"]["driverless"])
        self.assertEqual(by["Old"]["state"], "stopped")
        self.assertFalse(by["Old"]["driverless"])
        self.assertTrue(by["Hall_Printer"]["driverless"])
        self.assertEqual(r["jobs"][0]["id"], "Office-12")

    def test_no_cups(self):
        with mock.patch.dict(os.environ, {"PATH": os.path.join(self.tmp, "none")}):
            r = M["printers.list"]({})
        self.assertFalse(r["available"])
        self.assertEqual(r["printers"], [])

    def test_default_and_unknown(self):
        M["printers.set_default"]({"printer": "Hall_Printer"})
        self.assertIn("lpoptions -d Hall_Printer", self.calls())
        for bad in ("Nope", "-x", "a b", "../x"):
            with self.assertRaises(BackendError):
                M["printers.set_default"]({"printer": bad})

    def test_print_file(self):
        r = M["print.file"]({"printer": "Office", "path": "doc.pdf", "copies": 2, "sides": "two-sided-long-edge"})
        self.assertEqual(r["job"], "Office-13")
        line = self.calls()[-1]
        self.assertTrue(line.startswith("lp -d Office -n 2 -t doc.pdf -o sides=two-sided-long-edge -- "), line)
        self.assertTrue(line.endswith("/home/doc.pdf"))

    def test_print_file_path_rules(self):
        for bad in ("../etc/passwd", "/etc/passwd", ".ssh/id_rsa", "missing.pdf"):
            with self.assertRaises(BackendError):
                M["print.file"]({"printer": "Office", "path": bad})
        self.assertEqual(self.calls(), [])

    def test_cancel(self):
        M["print.job.cancel"]({"job": "Office-12"})
        self.assertIn("cancel Office-12", self.calls())
        for bad in ("Office-99", "x", "-a"):
            with self.assertRaises(BackendError):
                M["print.job.cancel"]({"job": bad})


if __name__ == "__main__":
    unittest.main()
