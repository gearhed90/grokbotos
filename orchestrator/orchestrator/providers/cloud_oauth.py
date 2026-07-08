"""Generic OAuth 2.0 Device Authorization Grant (RFC 8628) provider base.

This implements *only* the auth handshake, and is deliberately not tied to
any specific cloud provider. Per docs/DECISIONS.md, wiring up a real
provider (Anthropic, OpenAI, ...) means creating a subclass that supplies
that provider's actual `device_authorization_endpoint`/`token_endpoint`/
`client_id`/`scope` (confirmed from their real docs) and implements
`complete_json()` against that provider's actual completion API -- none of
that exists yet. Do not invent endpoint values here; leave the provider
unconfigured rather than hardcode a guess.

`http_post` is injected (defaults to a real urllib-based implementation)
so the device-flow state machine can be unit tested without a network call
or a real provider.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable

from .base import AuthRequired, LLMProvider, ProviderNotReady, ProviderStatus

HttpPost = Callable[[str, dict], dict]


def _real_http_post(url: str, form_data: dict) -> dict:
    body = urllib.parse.urlencode(form_data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 - fixed http(s) endpoint supplied by caller
        return json.loads(resp.read().decode())


@dataclass
class _DeviceCodeState:
    device_code: str
    user_code: str
    verification_uri: str
    expires_at: float
    interval_seconds: int


class OAuthDeviceFlowProvider(LLMProvider):
    def __init__(
        self,
        provider_id: str,
        model_id: str,
        device_authorization_endpoint: str,
        token_endpoint: str,
        client_id: str,
        scope: str,
        http_post: HttpPost = _real_http_post,
    ):
        self.provider_id = provider_id
        self.model_id = model_id
        self._device_authorization_endpoint = device_authorization_endpoint
        self._token_endpoint = token_endpoint
        self._client_id = client_id
        self._scope = scope
        self._http_post = http_post

        self._pending: _DeviceCodeState | None = None
        self._access_token: str | None = None

    def status(self) -> ProviderStatus:
        if self._access_token is not None:
            return ProviderStatus.READY
        return ProviderStatus.AUTH_REQUIRED

    def ensure_ready(self) -> None:
        if self._access_token is not None:
            return

        if self._pending is None:
            self._pending = self._request_device_code()

        if time.time() > self._pending.expires_at:
            self._pending = None
            raise AuthRequired(
                self.provider_id,
                verification_uri="",
                user_code="",
                expires_in_seconds=0,
            )

        token = self._poll_token_once(self._pending)
        if token is not None:
            self._access_token = token
            self._pending = None
            return

        raise AuthRequired(
            self.provider_id,
            verification_uri=self._pending.verification_uri,
            user_code=self._pending.user_code,
            expires_in_seconds=int(self._pending.expires_at - time.time()),
        )

    def complete_json(self, prompt: str, schema: dict) -> dict:
        raise NotImplementedError(
            f"{self.provider_id}: no concrete completion API wired up yet "
            "-- OAuthDeviceFlowProvider only implements the auth handshake, "
            "see module docstring."
        )

    def _request_device_code(self) -> _DeviceCodeState:
        resp = self._http_post(
            self._device_authorization_endpoint,
            {"client_id": self._client_id, "scope": self._scope},
        )
        return _DeviceCodeState(
            device_code=resp["device_code"],
            user_code=resp["user_code"],
            verification_uri=resp.get("verification_uri", resp.get("verification_uri_complete", "")),
            expires_at=time.time() + resp.get("expires_in", 600),
            interval_seconds=resp.get("interval", 5),
        )

    def _poll_token_once(self, pending: _DeviceCodeState) -> str | None:
        try:
            resp = self._http_post(
                self._token_endpoint,
                {
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "device_code": pending.device_code,
                    "client_id": self._client_id,
                },
            )
        except Exception as exc:  # noqa: BLE001 - surfaced via ProviderNotReady
            raise ProviderNotReady(str(exc)) from exc

        if "access_token" in resp:
            return resp["access_token"]

        # RFC 8628 6.1: authorization_pending / slow_down are expected
        # while the user hasn't finished the browser step yet.
        error = resp.get("error")
        if error in ("authorization_pending", "slow_down"):
            return None
        raise ProviderNotReady(f"{self.provider_id}: device flow error '{error}'")
