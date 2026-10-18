import json
import subprocess
import unittest

from orchestrator.webshell import wm


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], returncode=returncode, stdout=stdout, stderr=stderr)


def _tree(*firefox_ids, other_ids=()):
    """Build a minimal sway get_tree-shaped JSON string with the given
    firefox window IDs plus some non-firefox noise (workspaces etc.)."""
    nodes = [{"id": i, "app_id": "firefox", "nodes": [], "floating_nodes": []} for i in firefox_ids]
    nodes += [{"id": i, "app_id": "foot", "nodes": [], "floating_nodes": []} for i in other_ids]
    return json.dumps(
        {
            "id": 0,
            "nodes": [
                {"id": 1, "type": "workspace", "nodes": nodes, "floating_nodes": []},
            ],
            "floating_nodes": [],
        }
    )


class TestFirefoxWindowIds(unittest.TestCase):
    def test_parses_firefox_ids_from_tree(self):
        def fake_run(argv, **kw):
            self.assertEqual(argv, ["swaymsg", "-t", "get_tree"])
            return _completed(stdout=_tree(101, 102, other_ids=(50,)))

        ids = wm.firefox_window_ids(run=fake_run)

        self.assertEqual(ids, {101, 102})

    def test_finds_firefox_windows_in_floating_nodes_too(self):
        payload = json.dumps(
            {
                "id": 0,
                "nodes": [],
                "floating_nodes": [{"id": 7, "app_id": "firefox", "nodes": [], "floating_nodes": []}],
            }
        )

        ids = wm.firefox_window_ids(run=lambda argv, **kw: _completed(stdout=payload))

        self.assertEqual(ids, {7})

    def test_missing_swaymsg_returns_empty_set_not_raise(self):
        def fake_run(argv, **kw):
            raise FileNotFoundError("no swaymsg")

        self.assertEqual(wm.firefox_window_ids(run=fake_run), set())

    def test_nonzero_exit_returns_empty_set(self):
        ids = wm.firefox_window_ids(run=lambda argv, **kw: _completed(returncode=1, stderr="no sway ipc"))

        self.assertEqual(ids, set())

    def test_malformed_json_returns_empty_set(self):
        ids = wm.firefox_window_ids(run=lambda argv, **kw: _completed(stdout="not json{{"))

        self.assertEqual(ids, set())


class TestCloseNewFirefoxWindows(unittest.TestCase):
    def test_kills_only_windows_not_present_before(self):
        calls = []

        def fake_run(argv, **kw):
            calls.append(argv)
            if argv == ["swaymsg", "-t", "get_tree"]:
                return _completed(stdout=_tree(1, 2, 3))
            return _completed()

        wm.close_new_firefox_windows(before_ids={1, 2}, run=fake_run)

        kill_calls = [c for c in calls if c[0] == "swaymsg" and c[-1] == "kill"]
        self.assertEqual(kill_calls, [["swaymsg", "[con_id=3]", "kill"]])

    def test_no_new_windows_means_no_kill_calls(self):
        calls = []

        def fake_run(argv, **kw):
            calls.append(argv)
            if argv == ["swaymsg", "-t", "get_tree"]:
                return _completed(stdout=_tree(1, 2))
            return _completed()

        wm.close_new_firefox_windows(before_ids={1, 2}, run=fake_run)

        self.assertFalse(any(c[-1] == "kill" for c in calls))

    def test_kill_failure_is_swallowed(self):
        def fake_run(argv, **kw):
            if argv == ["swaymsg", "-t", "get_tree"]:
                return _completed(stdout=_tree(1, 2))
            raise subprocess.TimeoutExpired(cmd=argv, timeout=5)

        wm.close_new_firefox_windows(before_ids=set(), run=fake_run)  # must not raise

    def test_swaymsg_missing_entirely_is_a_safe_no_op(self):
        def fake_run(argv, **kw):
            raise FileNotFoundError("no swaymsg")

        wm.close_new_firefox_windows(before_ids={1}, run=fake_run)  # must not raise


if __name__ == "__main__":
    unittest.main()
