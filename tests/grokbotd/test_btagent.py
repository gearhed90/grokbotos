"""btagent.Handler: every BlueZ Agent1 request is decided by the user (consent) or refused."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "system_files", "usr", "lib", "grokbot"))
from grokbotd import btagent  # noqa: E402
from grokbotd.backends import BackendError  # noqa: E402

DEV = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_02"


class HandlerTest(unittest.TestCase):
    def mk(self, pin=None, answer=True):
        self.asked, self.shown = [], []

        def confirm(kind, ko, en, code):
            self.asked.append((kind, ko, en, code))
            return answer

        def notify(kind, ko, en, code):
            self.shown.append((kind, code))
        return btagent.Handler(DEV, "K380", pin, confirm, notify)

    def test_confirmation_goes_to_consent(self):
        h = self.mk()
        self.assertIsNone(h.call("RequestConfirmation", [DEV, 1234]))
        kind, ko, en, code = self.asked[0]
        self.assertEqual((kind, code), ("confirm", "001234"))
        self.assertIn("001234", ko)
        self.assertIn("K380", en)

    def test_confirmation_denied_rejects(self):
        h = self.mk(answer=False)
        with self.assertRaises(btagent.Rejected):
            h.call("RequestConfirmation", [DEV, 1234])
        with self.assertRaises(btagent.Rejected):
            h.call("RequestAuthorization", [DEV])

    def test_other_device_rejected(self):
        h = self.mk()
        with self.assertRaises(btagent.Rejected):
            h.call("RequestConfirmation", ["/org/bluez/hci0/dev_11_22_33_44_55_66", 1])
        with self.assertRaises(btagent.Rejected):
            h.call("AuthorizeService", ["/org/bluez/hci0/dev_11_22_33_44_55_66", "0000110b"])
        self.assertEqual(self.asked, [])

    def test_display_passkey_notifies(self):
        h = self.mk()
        h.call("DisplayPasskey", [DEV, 42, 0])
        h.call("DisplayPinCode", [DEV, "8812"])
        self.assertEqual(self.shown, [("display", "000042"), ("display", "8812")])

    def test_pin_requests(self):
        with self.assertRaises(btagent.Rejected):
            self.mk().call("RequestPinCode", [DEV])
        self.assertEqual(self.mk(pin="0000").call("RequestPinCode", [DEV]), "0000")
        self.assertEqual(self.mk(pin="123456").call("RequestPasskey", [DEV]), 123456)
        with self.assertRaises(btagent.Rejected):
            self.mk(pin="abc").call("RequestPasskey", [DEV])

    def test_check_pin(self):
        self.assertIsNone(btagent.check_pin(None))
        self.assertEqual(btagent.check_pin("0000"), "0000")
        for bad in ("00 00", "x" * 17, "1;2", 5):
            with self.assertRaises(BackendError):
                btagent.check_pin(bad)

    def test_unknown_method_rejected(self):
        with self.assertRaises(btagent.Rejected):
            self.mk().call("Bogus", [DEV])


if __name__ == "__main__":
    unittest.main()
