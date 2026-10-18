import subprocess
import unittest

from orchestrator.providers.base import AuthRequired, ModelNotInstalled, ProviderNotReady, ProviderStatus
from orchestrator.providers.cloud_oauth import OAuthDeviceFlowProvider
from orchestrator.providers.local_ollama import OllamaProvider


class TestOllamaProvider(unittest.TestCase):
    def test_not_installed_then_pull_makes_it_ready(self):
        calls = {"list_calls": 0, "pulled": False}

        def fake_get(url):
            calls["list_calls"] += 1
            if calls["pulled"]:
                return {"models": [{"name": "llama3:8b"}]}
            return {"models": []}

        def fake_run(argv):
            self.assertEqual(argv, ["ollama", "pull", "llama3:8b"])
            calls["pulled"] = True
            return subprocess.CompletedProcess(argv, returncode=0, stdout="", stderr="")

        provider = OllamaProvider("llama3:8b", http_get=fake_get, run=fake_run)

        self.assertEqual(provider.status(), ProviderStatus.MODEL_NOT_INSTALLED)
        provider.ensure_ready()
        self.assertEqual(provider.status(), ProviderStatus.READY)

    def test_log_hook_receives_pull_progress(self):
        lines = []

        def fake_get(url):
            return {"models": [{"name": "llama3:8b"}]} if fake_get.pulled else {"models": []}

        fake_get.pulled = False

        def fake_run(argv):
            fake_get.pulled = True
            return subprocess.CompletedProcess(argv, returncode=0, stdout="", stderr="")

        provider = OllamaProvider("llama3:8b", http_get=fake_get, run=fake_run, log=lines.append)

        provider.ensure_ready()

        joined = "\n".join(lines)
        self.assertIn("pull", joined)
        self.assertIn("준비 완료", joined)

    def test_daemon_unreachable_raises_model_not_installed_with_hint(self):
        def fake_get(url):
            raise ConnectionRefusedError("no daemon")

        provider = OllamaProvider("llama3:8b", http_get=fake_get)

        self.assertEqual(provider.status(), ProviderStatus.ERROR)
        with self.assertRaises(ModelNotInstalled) as ctx:
            provider.ensure_ready()
        self.assertIn("docs/LOCAL_SETUP.md", str(ctx.exception))

    def test_pull_failure_raises_model_not_installed(self):
        def fake_get(url):
            return {"models": []}

        def fake_run(argv):
            return subprocess.CompletedProcess(argv, returncode=1, stdout="", stderr="network error")

        provider = OllamaProvider("llama3:8b", http_get=fake_get, run=fake_run)

        with self.assertRaises(ModelNotInstalled):
            provider.ensure_ready()

    def test_complete_json_requires_ready_first(self):
        provider = OllamaProvider("llama3:8b", http_get=lambda url: {"models": []})

        with self.assertRaises(ProviderNotReady):
            provider.complete_json("hello", schema={"type": "object"})

    def test_complete_json_parses_response_field(self):
        def fake_get(url):
            return {"models": [{"name": "llama3:8b"}]}

        def fake_post(url, body):
            self.assertEqual(body["format"], "json")
            self.assertIn("hello", body["prompt"])
            return {"response": '{"goal": "say hi"}'}

        provider = OllamaProvider("llama3:8b", http_get=fake_get, http_post=fake_post)

        result = provider.complete_json("hello", schema={"type": "object"})

        self.assertEqual(result, {"goal": "say hi"})


class TestOAuthDeviceFlowProvider(unittest.TestCase):
    def _provider(self, http_post):
        return OAuthDeviceFlowProvider(
            provider_id="fake-cloud",
            model_id="fake-model",
            device_authorization_endpoint="https://example.invalid/device",
            token_endpoint="https://example.invalid/token",
            client_id="test-client",
            scope="inference",
            http_post=http_post,
        )

    def test_first_call_requests_device_code_and_raises_auth_required(self):
        def fake_post(url, data):
            if url.endswith("/device"):
                return {
                    "device_code": "dc-1",
                    "user_code": "ABCD-1234",
                    "verification_uri": "https://example.invalid/activate",
                    "expires_in": 600,
                    "interval": 5,
                }
            return {"error": "authorization_pending"}

        provider = self._provider(fake_post)

        with self.assertRaises(AuthRequired) as ctx:
            provider.ensure_ready()

        self.assertEqual(ctx.exception.user_code, "ABCD-1234")
        self.assertEqual(provider.status(), ProviderStatus.AUTH_REQUIRED)

    def test_pending_authorization_keeps_raising_auth_required(self):
        def fake_post(url, data):
            if url.endswith("/device"):
                return {
                    "device_code": "dc-1",
                    "user_code": "ABCD-1234",
                    "verification_uri": "https://example.invalid/activate",
                    "expires_in": 600,
                    "interval": 5,
                }
            return {"error": "authorization_pending"}

        provider = self._provider(fake_post)

        with self.assertRaises(AuthRequired):
            provider.ensure_ready()
        with self.assertRaises(AuthRequired):
            provider.ensure_ready()  # still pending, must not crash on retry

    def test_user_completes_login_makes_provider_ready(self):
        state = {"authorized": False}

        def fake_post(url, data):
            if url.endswith("/device"):
                return {
                    "device_code": "dc-1",
                    "user_code": "ABCD-1234",
                    "verification_uri": "https://example.invalid/activate",
                    "expires_in": 600,
                    "interval": 5,
                }
            if state["authorized"]:
                return {"access_token": "tok-123"}
            return {"error": "authorization_pending"}

        provider = self._provider(fake_post)

        with self.assertRaises(AuthRequired):
            provider.ensure_ready()

        state["authorized"] = True
        provider.ensure_ready()

        self.assertEqual(provider.status(), ProviderStatus.READY)

    def test_complete_json_not_implemented_for_generic_base(self):
        provider = self._provider(http_post=lambda url, data: {})

        with self.assertRaises(NotImplementedError):
            provider.complete_json("hi", schema={})


if __name__ == "__main__":
    unittest.main()
