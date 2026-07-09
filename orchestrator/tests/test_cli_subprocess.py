import subprocess
import unittest
from unittest.mock import patch

from orchestrator.providers.base import ExternalLoginRequired, ProviderNotReady, ProviderStatus
from orchestrator.providers.cli_subprocess import CliSubprocessProvider


class _FakeCliProvider(CliSubprocessProvider):
    provider_id = "fake-cli"
    cli_binary = "fakecli"
    login_command = "fakecli login"
    install_argv = ["npm", "install", "-g", "fakecli-pkg"]


def _ok(argv, stdout=""):
    return subprocess.CompletedProcess(argv, returncode=0, stdout=stdout, stderr="")


def _fail(argv, stderr="not found"):
    return subprocess.CompletedProcess(argv, returncode=1, stdout="", stderr=stderr)


class TestCliSubprocessProvider(unittest.TestCase):
    def test_binary_missing_triggers_install_then_login_check(self):
        calls = []

        def fake_run(argv):
            calls.append(argv)
            if argv == ["fakecli", "--version"]:
                return _fail(argv)  # never becomes available in this test
            if argv[0] == "npm":
                return _ok(argv)
            return _fail(argv)

        provider = _FakeCliProvider(run=fake_run)

        with self.assertRaises(ExternalLoginRequired):
            provider.ensure_ready()

        self.assertIn(["npm", "install", "-g", "fakecli-pkg"], calls)

    def test_binary_present_but_not_logged_in_raises_external_login_required(self):
        def fake_run(argv):
            if argv == ["fakecli", "--version"]:
                return _ok(argv)
            return _fail(argv, stderr="not authenticated")  # smoke-test prompt fails

        provider = _FakeCliProvider(run=fake_run)

        with self.assertRaises(ExternalLoginRequired) as ctx:
            provider.ensure_ready()
        self.assertEqual(ctx.exception.login_command, "fakecli login")

    def test_successful_smoke_test_marks_ready_and_caches(self):
        calls = []

        def fake_run(argv):
            calls.append(argv)
            return _ok(argv, stdout="ok")

        provider = _FakeCliProvider(run=fake_run)

        provider.ensure_ready()
        self.assertEqual(provider.status(), ProviderStatus.READY)

        calls.clear()
        provider.ensure_ready()  # must not re-run the CLI once verified
        self.assertEqual(calls, [])

    def test_complete_json_requires_ready(self):
        provider = _FakeCliProvider(run=lambda argv: _fail(argv))

        with self.assertRaises(ProviderNotReady):
            provider.complete_json("hi", schema={})

    def test_complete_json_parses_stdout_as_json(self):
        def fake_run(argv):
            if argv == ["fakecli", "--version"]:
                return _ok(argv)
            if "-p" in argv:
                prompt = argv[argv.index("-p") + 1]
                if "ok" in prompt.lower():
                    return _ok(argv, stdout="ok")
                return _ok(argv, stdout='{"goal": "hi"}')
            return _fail(argv)

        provider = _FakeCliProvider(run=fake_run)
        provider.ensure_ready()

        result = provider.complete_json("hi", schema={"type": "object"})

        self.assertEqual(result, {"goal": "hi"})

    def test_no_install_argv_raises_external_login_required_when_binary_missing(self):
        class _NoInstall(CliSubprocessProvider):
            provider_id = "no-install-cli"
            cli_binary = "noinstallcli"
            login_command = "noinstallcli login"
            install_argv = None

        provider = _NoInstall(run=lambda argv: _fail(argv))

        with self.assertRaises(ExternalLoginRequired):
            provider.ensure_ready()

    def test_set_env_merged_into_default_runner_and_invalidates_ready_cache(self):
        provider = _FakeCliProvider(run=lambda argv: _ok(argv, stdout="ok"))
        provider._verified_ready = True

        provider.set_env("SOME_TOKEN", "secret-value")

        self.assertFalse(provider._verified_ready)
        self.assertEqual(provider._extra_env["SOME_TOKEN"], "secret-value")

    @patch("subprocess.run")
    def test_default_runner_passes_extra_env_merged_with_os_environ(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], returncode=0, stdout="ok", stderr="")
        provider = _FakeCliProvider()  # no injected run -> uses real _default_run
        provider.set_env("SOME_TOKEN", "secret-value")

        provider._default_run(["fakecli", "--version"])

        called_env = mock_run.call_args.kwargs["env"]
        self.assertEqual(called_env["SOME_TOKEN"], "secret-value")

    @patch("subprocess.run")
    def test_interactive_login_streams_real_stdio_and_reports_exit_code(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], returncode=0)
        provider = _FakeCliProvider()
        provider.set_env("SOME_TOKEN", "secret-value")

        success = provider.interactive_login()

        self.assertTrue(success)
        args, kwargs = mock_run.call_args
        self.assertEqual(args[0], ["fakecli", "login"])
        self.assertNotIn("capture_output", kwargs)  # real stdio, not captured
        self.assertEqual(kwargs["env"]["SOME_TOKEN"], "secret-value")


if __name__ == "__main__":
    unittest.main()
