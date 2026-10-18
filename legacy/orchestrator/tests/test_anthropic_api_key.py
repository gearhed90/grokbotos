import unittest

from orchestrator.providers.anthropic_api_key import AnthropicApiKeyProvider
from orchestrator.providers.base import ProviderNotReady, ProviderStatus, SecretRequired
from orchestrator.providers.secret_store import SecretStore


class _FakeSecretStore(SecretStore):
    def __init__(self, secrets: dict):
        self._secrets = secrets

    def get(self, name):
        return self._secrets.get(name)


class TestAnthropicApiKeyProvider(unittest.TestCase):
    def test_missing_key_raises_secret_required(self):
        provider = AnthropicApiKeyProvider(secret_store=_FakeSecretStore({}))

        self.assertEqual(provider.status(), ProviderStatus.AUTH_REQUIRED)
        with self.assertRaises(SecretRequired) as ctx:
            provider.ensure_ready()
        self.assertEqual(ctx.exception.secret_name, "ANTHROPIC_API_KEY")

    def test_present_key_is_ready(self):
        provider = AnthropicApiKeyProvider(secret_store=_FakeSecretStore({"ANTHROPIC_API_KEY": "sk-ant-x"}))

        self.assertEqual(provider.status(), ProviderStatus.READY)
        provider.ensure_ready()  # must not raise

    def test_complete_json_requires_ready(self):
        provider = AnthropicApiKeyProvider(secret_store=_FakeSecretStore({}))

        with self.assertRaises(ProviderNotReady):
            provider.complete_json("hi", schema={})

    def test_complete_json_sends_api_key_header_and_parses_response(self):
        def fake_post(url, headers, body):
            self.assertEqual(headers["x-api-key"], "sk-ant-x")
            self.assertEqual(url, "https://api.anthropic.com/v1/messages")
            return {"content": [{"type": "text", "text": '{"goal": "hi"}'}]}

        provider = AnthropicApiKeyProvider(
            secret_store=_FakeSecretStore({"ANTHROPIC_API_KEY": "sk-ant-x"}), http_post=fake_post
        )

        result = provider.complete_json("hi", schema={"type": "object"})

        self.assertEqual(result, {"goal": "hi"})


if __name__ == "__main__":
    unittest.main()
