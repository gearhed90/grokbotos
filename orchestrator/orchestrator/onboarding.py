"""ROADMAP.md 2.1/2.2 -- the gate before the prompt input screen.

The closed-loop pipeline can't do anything without a working LLMProvider,
so the boot shell must not show a prompt box until one is actually
connected. This module is the provider-agnostic logic layer for that:
what providers are offered, how each one's connection flow actually
completes, and remembering the choice across boots. `onboarding_cli.py`
is the (console, for now) UI on top of this.

Both Claude and Grok now use the same primary flow -- `interactive_login()`
runs `claude login` / `grok login` with real stdio, so the CLI's own
browser-opening behavior (Firefox, baked into the image -- see
docs/DECISIONS.md) handles it directly, same as running either command
from a normal terminal. `connect_claude_with_token()` (paste a
`claude setup-token` output) is kept as a fallback for when no graphical
session is available yet (very early boot, recovery console, etc.), per
Anthropic's own documented headless-auth path -- not the primary path
once a local browser exists.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path

from .providers.base import ExternalLoginRequired, LLMProvider, ProviderNotReady
from .providers.cli_subprocess import CliSubprocessProvider
from .providers.claude_cli import ClaudeCliProvider
from .providers.local_ollama import OllamaProvider
from .providers.xai_grok import GrokCliProvider

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "oais" / "provider.json"
DEFAULT_OLLAMA_MODEL = "llama3"


@dataclass(frozen=True)
class ProviderChoice:
    id: str
    label: str
    kind: str  # "token_paste" | "device_flow" | "auto_install" | "custom"


CHOICES: list[ProviderChoice] = [
    ProviderChoice("claude", "Claude (Anthropic)", "token_paste"),
    ProviderChoice("grok", "Grok (xAI)", "device_flow"),
    ProviderChoice("ollama", "로컬 모델 (Ollama)", "auto_install"),
    ProviderChoice("custom", "다른 CLI 기반 LLM 직접 추가", "custom"),
]


@dataclass
class SavedConnection:
    choice_id: str
    model_id: str | None = None
    custom_cli_binary: str | None = None
    custom_login_command: str | None = None
    custom_install_argv: list[str] | None = None


class CustomCliProvider(CliSubprocessProvider):
    """A user-supplied CLI-based LLM -- ROADMAP.md 2.2's "추가적으로 다른
    LLM을 CLI로 설치". Reuses the exact same install/login/subprocess
    machinery as the built-in Claude/Grok providers; the user just
    supplies the binary name and commands instead of them being baked in.
    """

    def __init__(
        self,
        provider_id: str,
        cli_binary: str,
        login_command: str,
        install_argv: list[str] | None = None,
        **kwargs,
    ):
        self.provider_id = provider_id
        self.cli_binary = cli_binary
        self.login_command = login_command
        self.install_argv = install_argv
        super().__init__(**kwargs)


def save_connection(conn: SavedConnection, path: Path = DEFAULT_CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dataclasses.asdict(conn), ensure_ascii=False, indent=2))


def load_connection(path: Path = DEFAULT_CONFIG_PATH) -> SavedConnection | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return SavedConnection(**data)


def build_provider(conn: SavedConnection) -> LLMProvider:
    """Reconstruct the right provider instance from a saved connection
    record. Doesn't re-authenticate -- callers still need ensure_ready()
    (Claude needs its token re-applied first; see get_active_provider)."""
    if conn.choice_id == "claude":
        return ClaudeCliProvider()
    if conn.choice_id == "grok":
        return GrokCliProvider()
    if conn.choice_id == "ollama":
        return OllamaProvider(model_id=conn.model_id or DEFAULT_OLLAMA_MODEL)
    if conn.choice_id == "custom":
        return CustomCliProvider(
            provider_id=f"custom-{conn.custom_cli_binary}",
            cli_binary=conn.custom_cli_binary,
            login_command=conn.custom_login_command,
            install_argv=conn.custom_install_argv,
        )
    raise ValueError(f"unknown choice_id {conn.choice_id!r}")


def get_active_provider(path: Path = DEFAULT_CONFIG_PATH) -> LLMProvider | None:
    """Load the saved connection, if any, and re-verify it's still ready
    (token could've expired, CLI could've been uninstalled, Ollama daemon
    could be down). Returns None either way the caller needs to run the
    connection flow again -- nothing saved, or what's saved doesn't work
    anymore. Claude is a special case: a bare CLAUDE_CODE_OAUTH_TOKEN
    can't be recovered from disk (never persisted, on purpose -- it's a
    credential), so a saved Claude connection can only be confirmed
    still-ready if `claude login`'s own stored session is still valid,
    not via the token-paste path this module drove originally."""
    conn = load_connection(path)
    if conn is None:
        return None
    provider = build_provider(conn)
    try:
        provider.ensure_ready()
    except ProviderNotReady:
        return None
    return provider


def connect_claude_via_browser(provider: ClaudeCliProvider | None = None) -> ClaudeCliProvider:
    """Primary Claude connection path now that a local browser is baked
    into the image: same shape as connect_grok() -- try silently first,
    otherwise run `claude login` with real stdio so its own browser-open
    behavior takes over."""
    provider = provider or ClaudeCliProvider()
    try:
        provider.ensure_ready()
        return provider
    except ExternalLoginRequired:
        pass

    if not provider.interactive_login():
        raise ExternalLoginRequired(
            provider.provider_id, provider.login_command, detail="`claude login` exited non-zero"
        )
    provider.ensure_ready()
    return provider


def connect_claude_with_token(token: str, provider: ClaudeCliProvider | None = None) -> ClaudeCliProvider:
    """Fallback path: no graphical session yet, or the user just prefers
    it. See module docstring."""
    provider = provider or ClaudeCliProvider()
    provider.authenticate_with_token(token)
    provider.ensure_ready()  # raises ExternalLoginRequired if the token doesn't actually work
    return provider


def connect_grok(provider: GrokCliProvider | None = None) -> GrokCliProvider:
    """Try silently first (already logged in from a previous session),
    otherwise drive the real device-code flow interactively."""
    provider = provider or GrokCliProvider()
    try:
        provider.ensure_ready()
        return provider
    except ExternalLoginRequired:
        pass

    if not provider.interactive_login():
        raise ExternalLoginRequired(
            provider.provider_id, provider.login_command, detail="`grok login` exited non-zero"
        )
    provider.ensure_ready()
    return provider


def connect_ollama(model_id: str = DEFAULT_OLLAMA_MODEL, provider: OllamaProvider | None = None) -> OllamaProvider:
    provider = provider or OllamaProvider(model_id=model_id)
    provider.ensure_ready()  # auto-installs the daemon's model via `ollama pull`
    return provider


def connect_custom(
    provider_id: str,
    cli_binary: str,
    login_command: str,
    install_argv: list[str] | None = None,
    provider: CliSubprocessProvider | None = None,
) -> CliSubprocessProvider:
    provider = provider or CustomCliProvider(provider_id, cli_binary, login_command, install_argv)
    try:
        provider.ensure_ready()
        return provider
    except ExternalLoginRequired:
        pass

    if not provider.interactive_login():
        raise ExternalLoginRequired(provider.provider_id, login_command, detail=f"`{login_command}` exited non-zero")
    provider.ensure_ready()
    return provider
