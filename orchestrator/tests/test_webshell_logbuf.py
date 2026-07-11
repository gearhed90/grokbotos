import threading
import time
import unittest

from orchestrator.webshell.logbuf import LogBuffer


class TestLogBuffer(unittest.TestCase):
    def test_append_then_since_returns_new_entries_only(self):
        buf = LogBuffer()
        buf.append("first")
        buf.append("second")

        entries = buf.since(-1)

        self.assertEqual([text for _id, text in entries], ["first", "second"])

    def test_since_excludes_entries_already_seen(self):
        buf = LogBuffer()
        buf.append("first")
        [first_id] = [i for i, _ in buf.since(-1)]
        buf.append("second")

        entries = buf.since(first_id)

        self.assertEqual([text for _id, text in entries], ["second"])

    def test_wait_for_more_returns_immediately_if_already_available(self):
        buf = LogBuffer()
        buf.append("already here")

        entries = buf.wait_for_more(-1, timeout=5.0)

        self.assertEqual([text for _id, text in entries], ["already here"])

    def test_wait_for_more_times_out_with_empty_list_if_nothing_new(self):
        buf = LogBuffer()

        start = time.monotonic()
        entries = buf.wait_for_more(-1, timeout=0.2)
        elapsed = time.monotonic() - start

        self.assertEqual(entries, [])
        self.assertGreaterEqual(elapsed, 0.15)

    def test_wait_for_more_wakes_up_when_a_line_is_appended_from_another_thread(self):
        buf = LogBuffer()
        result = {}

        def _waiter():
            result["entries"] = buf.wait_for_more(-1, timeout=5.0)

        thread = threading.Thread(target=_waiter)
        thread.start()
        time.sleep(0.05)  # let the waiter block first
        buf.append("woke you up")
        thread.join(timeout=5.0)

        self.assertEqual([text for _id, text in result["entries"]], ["woke you up"])

    def test_maxlen_evicts_oldest_entries(self):
        buf = LogBuffer(maxlen=3)
        for i in range(5):
            buf.append(f"line{i}")

        entries = buf.since(-1)

        self.assertEqual([text for _id, text in entries], ["line2", "line3", "line4"])


if __name__ == "__main__":
    unittest.main()
