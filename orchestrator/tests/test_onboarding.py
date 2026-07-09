import tempfile
import unittest
from pathlib import Path

from orchestrator.providers.base import ExternalLoginRequired, ProviderStatus
from orchestrator import onboarding
from orchestrator.onboarding import (
    CustomCliProvider,
    SavedConnection,
    build_provider,
    connect_claude_via_browser,
    connect_claude_with_token,
    connect_custom,
    connect_grok,
    connect_ollama,
    get_active_provider,
    load_connection,
    save_connection,
)
from orchestrator.providers.claude_cli import ClaudeCliProvider
from orchestrator.providers.local_ollama import OllamaProvider
from orchestrator.providers.xai_grok import GrokCliProvider


class _FakeProvider:
    """Minimal stand-in implementing just what onboarding's connect_*
    functions call, so device-flow/interactive paths are testable without
    a real terminal or CLI."""

    provider_id = "fake"
    login_command = "fake login"

    def __init__(self, ready_after_login=True, ensure_ready_raises_first=True):
        self._ready = not ensure_ready_raises_first
        self._ready_after_login = ready_after_login
        self.interactive_login_called = False
        self.ensure_ready_calls = 0

    def ensure_ready(self):
        self.ensure_ready_calls += 1
        if not self._ready:
            raise ExternalLoginRequired(self.provider_id, self.login_command, detail="not logged in")

    def interactive_login(self):
        self.interactive_login_called = True
        self._ready = self._ready_after_login
        return self._ready_after_login


class TestConnectionPersistence(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "provider.json"

    def test_load_missing_file_returns_none(self):
        self.assertIsNone(load_connection(self.path))

    def test_save_then_load_round_trips(self):
        conn = SavedConnection(choice_id="ollama", model_id="llama3")

        save_connection(conn, self.path)
        loaded = load_connection(self.path)

        self.assertEqual(loaded, conn)

    def test_corrupted_file_returns_none_not_raise(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("not json{{{")

        self.assertIsNone(load_connection(self.path))


class TestBuildProvider(unittest.TestCase):
    def test_claude(self):
        self.assertIsInstance(build_provider(SavedConnection(choice_id="claude")), ClaudeCliProvider)

    def test_grok(self):
        self.assertIsInstance(build_provider(SavedConnection(choice_id="grok")), GrokCliProvider)

    def test_ollama_uses_saved_model_id(self):
        provider = build_provider(SavedConnection(choice_id="ollama", model_id="mistral"))
        self.assertIsInstance(provider, OllamaProvider)
        self.assertEqual(provider.model_id, "mistral")

    def test_custom_reconstructs_cli_config(self):
        conn = SavedConnection(
            choice_id="custom",
            custom_cli_binary="mycli",
            custom_login_command="mycli login",
            custom_install_argv=["pip", "install", "mycli"],
        )
        provider = build_provider(conn)
        self.assertIsInstance(provider, CustomCliProvider)
        self.assertEqual(provider.cli_binary, "mycli")
        self.assertEqual(provider.login_command, "mycli login")

    def test_unknown_choice_id_raises(self):
        with self.assertRaises(ValueError):
            build_provider(SavedConnection(choice_id="nope"))


class TestGetActiveProvider(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "provider.json"

    def test_nothing_saved_returns_none(self):
        self.assertIsNone(get_active_provider(self.path))

    def test_saved_but_no_longer_ready_returns_none(self):
        save_connection(SavedConnection(choice_id="ollama", model_id="llama3"), self.path)

        # OllamaProvider.ensure_ready() will hit a real (nonexistent in this
        # sandbox) daemon and raise ModelNotInstalled (a ProviderNotReady) --
        # exactly the "no longer ready" case this is meant to cover.
        self.assertIsNone(get_active_provider(self.path))


class TestConnectGrok(unittest.TestCase):
    def test_already_logged_in_skips_interactive_login(self):
        fake = _FakeProvider(ensure_ready_raises_first=False)

        result = connect_grok(provider=fake)

        self.assertIs(result, fake)
        self.assertFalse(fake.interactive_login_called)

    def test_not_logged_in_drives_interactive_login_then_reverifies(self):
        fake = _FakeProvider(ensure_ready_raises_first=True, ready_after_login=True)

        connect_grok(provider=fake)

        self.assertTrue(fake.interactive_login_called)
        self.assertEqual(fake.ensure_ready_calls, 2)  # once failing, once after login

    def test_interactive_login_failure_raises(self):
        fake = _FakeProvider(ensure_ready_raises_first=True, ready_after_login=False)

        with self.assertRaises(ExternalLoginRequired):
            connect_grok(provider=fake)


class TestConnectClaudeViaBrowser(unittest.TestCase):
    """Primary Claude path now that a browser is baked into the image --
    same shape as connect_grok()."""

    def test_already_logged_in_skips_interactive_login(self):
        fake = _FakeProvider(ensure_ready_raises_first=False)

        result = connect_claude_via_browser(provider=fake)

        self.assertIs(result, fake)
        self.assertFalse(fake.interactive_login_called)

    def test_not_logged_in_drives_browser_login_then_reverifies(self):
        fake = _FakeProvider(ensure_ready_raises_first=True, ready_after_login=True)

        connect_claude_via_browser(provider=fake)

        self.assertTrue(fake.interactive_login_called)
        self.assertEqual(fake.ensure_ready_calls, 2)

    def test_browser_login_failure_raises(self):
        fake = _FakeProvider(ensure_ready_raises_first=True, ready_after_login=False)

        with self.assertRaises(ExternalLoginRequired):
            connect_claude_via_browser(provider=fake)


class TestConnectClaudeWithToken(unittest.TestCase):
    def test_sets_token_and_verifies(self):
        calls = []

        class _Fake:
            provider_id = "anthropic-claude-code"

            def authenticate_with_token(self, token):
                calls.append(("auth", token))

            def ensure_ready(self):
                calls.append(("verify",))

        fake = _Fake()
        result = connect_claude_with_token("tok-123", provider=fake)

        self.assertIs(result, fake)
        self.assertEqual(calls, [("auth", "tok-123"), ("verify",)])


class TestConnectOllama(unittest.TestCase):
    def test_calls_ensure_ready(self):
        calls = []

        class _Fake:
            def ensure_ready(self):
                calls.append("ready")

        connect_ollama(provider=_Fake())

        self.assertEqual(calls, ["ready"])


class TestConnectCustom(unittest.TestCase):
    def test_drives_interactive_login_when_needed(self):
        fake = _FakeProvider(ensure_ready_raises_first=True, ready_after_login=True)

        connect_custom("my-llm", "mycli", "mycli login", provider=fake)

        self.assertTrue(fake.interactive_login_called)


if __name__ == "__main__":
    unittest.main()
