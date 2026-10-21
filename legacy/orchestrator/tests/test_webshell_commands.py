import tempfile
import time
import unittest
from pathlib import Path

from orchestrator.registry.db import AppRegistry
from orchestrator.webshell import commands
from orchestrator.webshell.state import ConnectionState


def _wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class _FakeProvider:
    provider_id = "fake"
    model_id = None


class _CompletedProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _DispatchTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.config_path = Path(self._tmp.name) / "provider.json"
        self.registry = AppRegistry(":memory:")
        self.addCleanup(self.registry.close)
        self.state = ConnectionState()

    def _dispatch(self, text, **kw):
        return commands.dispatch(
            text, state=self.state, registry=self.registry, config_path=self.config_path, **kw
        )


class TestDispatchRouting(_DispatchTestCase):
    def test_unknown_command_returns_error_pointing_at_help(self):
        result = self._dispatch("/nope")

        self.assertEqual(result["status"], "error")
        self.assertIn("/help", result["message"])

    def test_every_dispatched_command_is_logged(self):
        lines = []

        self._dispatch("/help", log=lines.append)

        self.assertIn("/help", lines[0])

    def test_help_lists_all_built_in_commands(self):
        result = self._dispatch("/help")

        self.assertEqual(result["status"], "success")
        for token in ("/llm", "/token", "/system", "/cli"):
            self.assertIn(token, result["message"])


class TestLlmCommand(_DispatchTestCase):
    def test_no_args_lists_choices(self):
        result = self._dispatch("/llm")

        self.assertEqual(result["status"], "success")
        self.assertIn("claude", result["message"])
        self.assertIn("grok", result["message"])

    def test_unknown_provider_id_returns_error(self):
        result = self._dispatch("/llm bogus")

        self.assertEqual(result["status"], "error")

    def test_valid_provider_starts_connecting_in_background(self):
        provider = _FakeProvider()

        result = self._dispatch("/llm claude", connectors={"claude": lambda **kw: provider})

        self.assertEqual(result["status"], "connecting")
        self.assertTrue(_wait_until(lambda: self.state.snapshot()["connected"]))
        self.assertEqual(self.state.snapshot()["choice_id"], "claude")

    def test_custom_without_cli_binary_returns_usage_error(self):
        result = self._dispatch("/llm custom")

        self.assertEqual(result["status"], "error")
        self.assertIn("사용법", result["message"])

    def test_custom_with_cli_binary_starts_connecting(self):
        provider = _FakeProvider()
        provider.cli_binary = "mycli"
        provider.login_command = "mycli login"
        provider.install_argv = None

        result = self._dispatch("/llm custom mycli", connectors={"custom": lambda **kw: provider})

        self.assertEqual(result["status"], "connecting")
        self.assertTrue(_wait_until(lambda: self.state.snapshot()["connected"]))


class TestTokenCommand(_DispatchTestCase):
    def test_missing_args_returns_usage_error(self):
        result = self._dispatch("/token")

        self.assertEqual(result["status"], "error")
        self.assertIn("사용법", result["message"])

    def test_non_claude_provider_rejected(self):
        result = self._dispatch("/token grok sometoken")

        self.assertEqual(result["status"], "error")

    def test_valid_token_starts_connecting_in_background(self):
        provider = _FakeProvider()

        result = self._dispatch("/token claude abc123", token_connector=lambda tok, log=None: provider)

        self.assertEqual(result["status"], "connecting")
        self.assertTrue(_wait_until(lambda: self.state.snapshot()["connected"]))
        self.assertEqual(self.state.snapshot()["choice_id"], "claude")


class TestSystemCommand(_DispatchTestCase):
    def test_bare_system_reports_disconnected(self):
        result = self._dispatch("/system")

        self.assertEqual(result["status"], "success")
        self.assertIn("없음", result["message"])

    def test_bare_system_reports_connected_provider(self):
        self.state.set_connected("claude", _FakeProvider())

        result = self._dispatch("/system")

        self.assertIn("claude", result["message"])

    def test_network_runs_nmcli_and_returns_output(self):
        seen = {}
        lines = []

        def _fake_run(argv, **kw):
            seen["argv"] = argv
            return _CompletedProcess(returncode=0, stdout="DEVICE  TYPE  STATE\neth0 ethernet connected\n")

        result = self._dispatch("/system network", run=_fake_run, log=lines.append)

        self.assertEqual(seen["argv"], ["nmcli", "device", "status"])
        self.assertEqual(result["status"], "success")
        self.assertIn("eth0", result["message"])
        self.assertTrue(any("nmcli" in line for line in lines))

    def test_network_missing_nmcli_returns_error(self):
        def _fake_run(argv, **kw):
            raise FileNotFoundError("no nmcli")

        result = self._dispatch("/system network", run=_fake_run)

        self.assertEqual(result["status"], "error")

    def test_network_nonzero_exit_returns_error(self):
        def _fake_run(argv, **kw):
            return _CompletedProcess(returncode=1, stderr="permission denied")

        result = self._dispatch("/system network", run=_fake_run)

        self.assertEqual(result["status"], "error")
        self.assertIn("permission denied", result["message"])

    def test_info_returns_success(self):
        result = self._dispatch("/system info")

        self.assertEqual(result["status"], "success")

    def test_unknown_subcommand_returns_error(self):
        result = self._dispatch("/system bogus")

        self.assertEqual(result["status"], "error")


class TestCliCommand(_DispatchTestCase):
    def test_spawns_default_terminal(self):
        calls = []

        result = self._dispatch("/cli", popen=lambda argv: calls.append(argv))

        self.assertEqual(result["status"], "success")
        self.assertEqual(calls, [commands.DEFAULT_TERMINAL_ARGV])

    def test_missing_terminal_binary_returns_error(self):
        def _fake_popen(argv):
            raise FileNotFoundError("no foot")

        result = self._dispatch("/cli", popen=_fake_popen)

        self.assertEqual(result["status"], "error")


if __name__ == "__main__":
    unittest.main()
