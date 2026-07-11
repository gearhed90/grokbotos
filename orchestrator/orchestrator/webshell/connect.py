"""Background-thread connection workers, called by `webshell/commands.py`'s
`/llm` and `/token` handlers (not a separate REST endpoint -- see
docs/DECISIONS.md on the unified slash-command router).

Each `connectors` entry is injectable (default: the real `onboarding.py`
functions) so tests can drive this without ever spawning a real CLI
subprocess or browser -- same DI pattern as the rest of the project.
`log`, if given, is a callable(str) -> None fed real install/login
progress for the shell UI's live log panel (webshell/logbuf.py).
"""

from __future__ import annotations

from .. import onboarding
from ..providers.base import ExternalLoginRequired, ProviderNotReady
from .state import ConnectionState


def _default_connectors() -> dict:
    return {
        "claude": lambda **kw: onboarding.connect_claude_via_browser(log=kw.get("log")),
        "grok": lambda **kw: onboarding.connect_grok(log=kw.get("log")),
        "ollama": lambda **kw: onboarding.connect_ollama(
            kw.get("model_id") or onboarding.DEFAULT_OLLAMA_MODEL, log=kw.get("log")
        ),
        "custom": lambda **kw: onboarding.connect_custom(
            f"custom-{kw['cli_binary']}",
            kw["cli_binary"],
            kw["login_command"],
            kw.get("install_argv"),
            log=kw.get("log"),
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
    log=None,
) -> None:
    connectors = connectors or _default_connectors()
    state.start_connecting(choice_id)
    if log:
        log(f"[llm] {choice_id} 연결 시작")

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
            log=log,
        )
    except ExternalLoginRequired as exc:
        # Only Claude has a documented headless token fallback (see
        # onboarding.py's module docstring) -- Grok/custom logins have no
        # such path yet, so there's nothing useful to paste for them.
        if log:
            log(f"[llm] {choice_id} 연결 실패: {exc}")
        state.set_error(str(exc), needs_token=(choice_id == "claude"))
        return
    except ProviderNotReady as exc:
        if log:
            log(f"[llm] {choice_id} 연결 실패: {exc}")
        state.set_error(str(exc))
        return
    except Exception as exc:  # noqa: BLE001 - see comment
        # This runs on a background thread (server.py's do_POST spawns it)
        # -- an uncaught exception here doesn't crash the process, it just
        # kills the thread silently, leaving ConnectionState stuck on
        # "connecting" forever with the UI showing no error at all. Real
        # example: npm missing from the image made install_argv raise a
        # bare FileNotFoundError, which neither except above catches
        # (2026-07-11, see docs/DECISIONS.md). Whatever the actual failure
        # is, it must reach the user instead of vanishing.
        if log:
            log(f"[llm] {choice_id} 연결 중 예상치 못한 오류: {type(exc).__name__}: {exc}")
        state.set_error(f"{type(exc).__name__}: {exc}")
        return

    if log:
        log(f"[llm] {choice_id} 연결 완료")
    _save(choice_id, provider, config_path)
    state.set_connected(choice_id, provider)


def run_connect_token(
    choice_id: str,
    token: str,
    state: ConnectionState,
    config_path,
    *,
    token_connector=None,
    log=None,
) -> None:
    token_connector = token_connector or onboarding.connect_claude_with_token
    state.start_connecting(choice_id)
    if log:
        log(f"[llm] {choice_id} 토큰으로 연결 시작")

    if choice_id != "claude":
        state.set_error("token fallback is only supported for claude right now")
        return

    try:
        provider = token_connector(token, log=log)
    except ExternalLoginRequired as exc:
        if log:
            log(f"[llm] {choice_id} 토큰 연결 실패: {exc}")
        state.set_error(str(exc), needs_token=True)
        return
    except Exception as exc:  # noqa: BLE001 - see run_connect's matching comment
        if log:
            log(f"[llm] {choice_id} 토큰 연결 중 예상치 못한 오류: {type(exc).__name__}: {exc}")
        state.set_error(f"{type(exc).__name__}: {exc}")
        return

    if log:
        log(f"[llm] {choice_id} 연결 완료")
    _save(choice_id, provider, config_path)
    state.set_connected(choice_id, provider)
