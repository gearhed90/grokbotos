"""Background-thread connection workers for the `/api/connect*` routes.

Each `connectors` entry is injectable (default: the real `onboarding.py`
functions) so tests can drive this without ever spawning a real CLI
subprocess or browser -- same DI pattern as the rest of the project.
"""

from __future__ import annotations

from .. import onboarding
from ..providers.base import ExternalLoginRequired, ProviderNotReady
from .state import ConnectionState


def _default_connectors() -> dict:
    return {
        "claude": lambda **kw: onboarding.connect_claude_via_browser(),
        "grok": lambda **kw: onboarding.connect_grok(),
        "ollama": lambda **kw: onboarding.connect_ollama(
            kw.get("model_id") or onboarding.DEFAULT_OLLAMA_MODEL
        ),
        "custom": lambda **kw: onboarding.connect_custom(
            f"custom-{kw['cli_binary']}",
            kw["cli_binary"],
            kw["login_command"],
            kw.get("install_argv"),
        ),
    }


def _save(choice_id: str, provider, config_path) -> None:
    model_id = getattr(provider, "model_id", None)
    if choice_id == "custom":
        conn = onboarding.SavedConnection(
            choice_id="custom",
            custom_cli_binary=provider.cli_binary,
            custom_login_command=provider.login_command,
            custom_install_argv=provider.install_argv,
        )
    else:
        conn = onboarding.SavedConnection(choice_id=choice_id, model_id=model_id)
    onboarding.save_connection(conn, config_path)


def run_connect(
    choice_id: str,
    state: ConnectionState,
    config_path,
    *,
    model_id: str | None = None,
    cli_binary: str | None = None,
    login_command: str | None = None,
    install_argv: list[str] | None = None,
    connectors: dict | None = None,
) -> None:
    connectors = connectors or _default_connectors()
    state.start_connecting(choice_id)

    connector = connectors.get(choice_id)
    if connector is None:
        state.set_error(f"unknown provider {choice_id!r}")
        return
    if choice_id == "custom" and (not cli_binary or not login_command):
        state.set_error("cli_binary/login_command required for a custom provider")
        return

    try:
        provider = connector(
            model_id=model_id,
            cli_binary=cli_binary,
            login_command=login_command,
            install_argv=install_argv,
        )
    except ExternalLoginRequired as exc:
        # Only Claude has a documented headless token fallback (see
        # onboarding.py's module docstring) -- Grok/custom logins have no
        # such path yet, so there's nothing useful to paste for them.
        state.set_error(str(exc), needs_token=(choice_id == "claude"))
        return
    except ProviderNotReady as exc:
        state.set_error(str(exc))
        return

    _save(choice_id, provider, config_path)
    state.set_connected(choice_id, provider)


def run_connect_token(
    choice_id: str,
    token: str,
    state: ConnectionState,
    config_path,
    *,
    token_connector=None,
) -> None:
    token_connector = token_connector or onboarding.connect_claude_with_token
    state.start_connecting(choice_id)

    if choice_id != "claude":
        state.set_error("token fallback is only supported for claude right now")
        return

    try:
        provider = token_connector(token)
    except ExternalLoginRequired as exc:
        state.set_error(str(exc), needs_token=True)
        return

    _save(choice_id, provider, config_path)
    state.set_connected(choice_id, provider)
