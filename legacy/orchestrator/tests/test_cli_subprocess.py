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

    @patch("subprocess.Popen")
    def test_interactive_login_streams_output_and_reports_exit_code(self, mock_popen_cls):
        mock_proc = mock_popen_cls.return_value
        mock_proc.stdout = iter(["some output line\n"])
        mock_proc.returncode = 0
        mock_proc.wait.return_value = 0
        provider = _FakeCliProvider()
        provider.set_env("SOME_TOKEN", "secret-value")

        success = provider.interactive_login()

        self.assertTrue(success)
        args, kwargs = mock_popen_cls.call_args
        self.assertEqual(args[0], ["fakecli", "login"])
        self.assertEqual(kwargs["stdout"], subprocess.PIPE)
        self.assertEqual(kwargs["stderr"], subprocess.STDOUT)
        self.assertEqual(kwargs["env"]["SOME_TOKEN"], "secret-value")

    @patch("subprocess.run")
    def test_install_call_gets_the_longer_timeout(self, mock_run):
        """Real bug, caught via the live log panel: a real `npm install -g`
        hit subprocess.TimeoutExpired at exactly 120s (2026-07-11,
        docs/DECISIONS.md) -- the same timeout used for the fast `-p`
        prompt calls was far too short for a real package install."""
        mock_run.return_value = subprocess.CompletedProcess([], returncode=0, stdout="ok", stderr="")
        provider = _FakeCliProvider()

        provider._default_run(provider.install_argv)

        self.assertEqual(mock_run.call_args.kwargs["timeout"], CliSubprocessProvider._INSTALL_TIMEOUT_SECONDS)
        self.assertGreater(CliSubprocessProvider._INSTALL_TIMEOUT_SECONDS, CliSubprocessProvider._PROMPT_TIMEOUT_SECONDS)

    @patch("subprocess.run")
    def test_prompt_call_gets_the_shorter_timeout(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], returncode=0, stdout="ok", stderr="")
        provider = _FakeCliProvider()

        provider._default_run(["fakecli", "-p", "hello"])

        self.assertEqual(mock_run.call_args.kwargs["timeout"], CliSubprocessProvider._PROMPT_TIMEOUT_SECONDS)

    def test_log_hook_receives_install_and_readiness_progress(self):
        """The shell UI's live log panel (webshell/logbuf.py) is fed by
        this hook -- without it, a slow install/login has zero visible
        progress beyond a static "연결 중..." message (2026-07-11 user
        feedback)."""
        lines = []
        installed = {"done": False}

        def fake_run(argv):
            if argv == ["fakecli", "--version"]:
                return _ok(argv) if installed["done"] else _fail(argv)
            if argv[0] == "npm":
                installed["done"] = True
                return _ok(argv)
            return _ok(argv, stdout="ok")

        provider = _FakeCliProvider(run=fake_run, log=lines.append)
        provider.ensure_ready()

        joined = "\n".join(lines)
        self.assertIn("설치 중", joined)
        self.assertIn("설치 완료", joined)
        self.assertIn("준비 완료", joined)

    def test_log_hook_reports_install_failure(self):
        lines = []

        def fake_run(argv):
            return _fail(argv)

        provider = _FakeCliProvider(run=fake_run, log=lines.append)

        with self.assertRaises(ExternalLoginRequired):
            provider.ensure_ready()

        self.assertTrue(any("설치 실패" in line for line in lines))

    @patch("subprocess.Popen")
    def test_log_hook_receives_interactive_login_progress(self, mock_popen_cls):
        """Real bug: `claude login` exited non-zero with zero visible
        output beyond the bare exit code, because interactive_login()
        inherited real stdio -- which in the GUI shell goes to an unread
        log file redirect, not anywhere the user can see (2026-07-11,
        docs/DECISIONS.md). Output must reach the log panel line by
        line, not just a start/end marker."""
        mock_proc = mock_popen_cls.return_value
        mock_proc.stdout = iter(["Visit: https://example.com/device?code=ABCD\n"])
        mock_proc.returncode = 0
        mock_proc.wait.return_value = 0
        lines = []
        provider = _FakeCliProvider(log=lines.append)

        provider.interactive_login()

        joined = "\n".join(lines)
        self.assertIn("fakecli login", joined)
        self.assertIn("https://example.com/device?code=ABCD", joined)
        self.assertIn("종료", joined)

    @patch("subprocess.Popen")
    def test_interactive_login_timeout_kills_process_and_logs(self, mock_popen_cls):
        mock_proc = mock_popen_cls.return_value
        mock_proc.stdout = iter([])
        mock_proc.wait.side_effect = [subprocess.TimeoutExpired(cmd="fakecli login", timeout=600), 0]
        lines = []
        provider = _FakeCliProvider(log=lines.append)

        with self.assertRaises(subprocess.TimeoutExpired):
            provider.interactive_login()

        mock_proc.kill.assert_called_once()
        self.assertTrue(any("시간 초과" in line for line in lines))

    def test_no_log_hook_is_a_safe_no_op(self):
        provider = _FakeCliProvider(run=lambda argv: _ok(argv, stdout="ok"))

        provider.ensure_ready()  # must not raise just because log wasn't given


if __name__ == "__main__":
    unittest.main()
