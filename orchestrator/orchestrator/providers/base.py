"""Provider abstraction for ROADMAP.md 2.2's "LLM 연동 방식 결정".

Decision (docs/DECISIONS.md): hybrid, but neither path uses the "obvious"
UX --

- Cloud providers connect via a login/auth flow, not a pasted API key
  (see cloud_oauth.py).
- Local models are fetched and installed automatically when selected, not
  manually by the user (see local_ollama.py).

This module only defines the shared contract both paths implement, so the
rest of the orchestrator (the eventual LLMBackedIntentAnalyzer, the
development agent in 2.6, etc.) can depend on `LLMProvider` without caring
which concrete provider is configured.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto


class ProviderStatus(Enum):
    READY = auto()
    AUTH_REQUIRED = auto()
    MODEL_NOT_INSTALLED = auto()
    ERROR = auto()


class ProviderNotReady(Exception):
    """Base for exceptions raised when complete_json() is called before
    ensure_ready() has succeeded."""


@dataclass
class AuthRequired(ProviderNotReady):
    """Cloud path: the user needs to complete a login flow.

    `verification_uri`/`user_code` are what the Phase 4 shell would render
    (RFC 8628 device flow) so the user can approve access in a browser on
    any device, not necessarily this one.
    """

    provider_id: str
    verification_uri: str
    user_code: str
    expires_in_seconds: int

    def __str__(self) -> str:  # pragma: no cover - trivial
        return (
            f"{self.provider_id}: visit {self.verification_uri} and enter "
            f"code {self.user_code} (expires in {self.expires_in_seconds}s)"
        )


@dataclass
class ModelNotInstalled(ProviderNotReady):
    """Local path: the model isn't pulled yet. ensure_ready() is expected
    to trigger the download itself rather than just raising this -- it's
    raised only if that download hasn't been (or couldn't be) completed."""

    provider_id: str
    model_id: str
    detail: str = ""

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.provider_id}: model '{self.model_id}' not installed. {self.detail}".strip()


@dataclass
class ProviderConfig:
    provider_id: str
    model_id: str
    extra: dict = field(default_factory=dict)


class LLMProvider(ABC):
    provider_id: str

    @abstractmethod
    def status(self) -> ProviderStatus:
        """Cheap, side-effect-free check of whether complete_json() would
        currently succeed."""

    @abstractmethod
    def ensure_ready(self) -> None:
        """Do whatever is needed to reach READY: for cloud providers, this
        starts (or checks progress of) the auth flow and raises
        AuthRequired until the user completes it; for local providers,
        this triggers the model download and blocks until it finishes, or
        raises ModelNotInstalled if it can't."""

    @abstractmethod
    def complete_json(self, prompt: str, schema: dict) -> dict:
        """Ask the model to produce JSON matching `schema`. Callers must
        call ensure_ready() first -- implementations should raise
        ProviderNotReady rather than silently degrading if it wasn't."""
