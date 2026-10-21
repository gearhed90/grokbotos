"""Anthropic provider: official API key auth, NOT Claude Code OAuth reuse.

docs/DECISIONS.md explains why: Anthropic added server-side enforcement
(rolled out Jan-Apr 2026) that blocks Claude Pro/Max/Team subscription
OAuth credentials from being used by anything other than Claude Code /
claude.ai, with account bans for violations. There is no legitimate way to
give this provider the "auth flow" treatment cloud_oauth.py or
xai_grok.py get.

What this *does* do to still avoid a bare "paste your key into a config
file" UX: the key is read through a `SecretStore` (secret_store.py)
rather than a hardcoded env var read inline here, so a future "connect
your Anthropic account" step in the Phase 4 shell can write to an OS
keyring and this provider doesn't change.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Callable

from .base import LLMProvider, ProviderNotReady, ProviderStatus, SecretRequired
from .secret_store import SecretStore

API_BASE_URL = "https://api.anthropic.com/v1"
API_VERSION = "2023-06-01"
SECRET_NAME = "ANTHROPIC_API_KEY"

HttpPost = Callable[[str, dict, dict], dict]  # url, headers, json body -> response


def _real_http_post(url: str, headers: dict, body: dict) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST", headers={**headers, "Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - fixed Anthropic endpoint
        return json.loads(resp.read().decode())


class AnthropicApiKeyProvider(LLMProvider):
    provider_id = "anthropic"

    def __init__(
        self,
        secret_store: SecretStore,
        model_id: str = "claude-sonnet-5",
        http_post: HttpPost = _real_http_post,
    ):
        self._secret_store = secret_store
        self.model_id = model_id
        self._http_post = http_post
        self._api_key: str | None = None

    def status(self) -> ProviderStatus:
        if self._api_key is not None:
            return ProviderStatus.READY
        key = self._secret_store.get(SECRET_NAME)
        if key:
            self._api_key = key
            return ProviderStatus.READY
        return ProviderStatus.AUTH_REQUIRED

    def ensure_ready(self) -> None:
        if self.status() is ProviderStatus.READY:
            return
        raise SecretRequired(
            self.provider_id,
            SECRET_NAME,
            detail="connect an Anthropic account (Console API key) before this provider can be used",
        )

    def complete_json(self, prompt: str, schema: dict) -> dict:
        if self.status() is not ProviderStatus.READY:
            raise ProviderNotReady(f"{self.provider_id}: call ensure_ready() first")

        schema_instruction = (
            "Respond with ONLY valid JSON matching this schema, no other text:\n" + json.dumps(schema)
        )
        resp = self._http_post(
            f"{API_BASE_URL}/messages",
            {"x-api-key": self._api_key, "anthropic-version": API_VERSION},
            {
                "model": self.model_id,
                "max_tokens": 4096,
                "system": schema_instruction,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        content = resp["content"][0]["text"]
        return json.loads(content)
