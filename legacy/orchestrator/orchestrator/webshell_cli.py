"""The actual boot-time shell (ROADMAP.md 2.1 입력 레이어 + Phase 4's gate).

    [부팅] -> sway -> 여기
      -> 로컬 웹서버 기동 (webshell/) -> Firefox --kiosk로 fullscreen 표시
      -> 저장된 연결 있음? -> 프롬프트 입력 활성화
      -> 없음 -> 하단 아이콘 독에서 Claude/Grok/Ollama/커스텀 선택 -> 연결 완료 시 활성화

Replaces the earlier plain-text `onboarding_cli.py` loop as the thing
sway actually launches: a real desktop-style page (prompt bar centered,
installed-app + LLM-connection icon dock along the bottom) instead of a
terminal menu, per explicit user feedback that a "설치되면 GUI가 표시되어야
한다" -- a numbered text menu in a terminal doesn't meet that bar.
`onboarding_cli.py` still exists and still works for headless use (SSH,
recovery console); the connection logic itself (`onboarding.py`) is
shared unchanged between both.

Voice input (2.1's other half) isn't implemented -- no STT engine has
been chosen yet (ROADMAP.md 2.1). Text-only for now.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

from . import onboarding
from .registry.db import AppRegistry
from .webshell.server import build_server
from .webshell.state import ConnectionState

DEFAULT_REGISTRY_PATH = Path.home() / ".local" / "share" / "oais" / "registry.db"
DEFAULT_PORT = 8765
FIREFOX_ARGV = ["firefox", "--kiosk"]

# If Firefox can't even start (crashes immediately, missing binary, no GPU
# support in a VM, etc.) this falls back to the old text shell instead of
# leaving sway showing nothing but its own cursor on a black screen --
# something visible beats a silent crash every time, and the fallback
# still runs the same real Orchestrator underneath (onboarding_cli.py).
FALLBACK_ARGV = ["foot", "-e", "python3", "-m", "orchestrator.onboarding_cli"]


def _initial_state(config_path: Path) -> ConnectionState:
    """Re-verify any saved connection at startup (token expired, CLI
    uninstalled, Ollama daemon down, etc.) using the exact same logic the
    text shell already relied on -- `onboarding.get_active_provider()`."""
    state = ConnectionState()
    conn = onboarding.load_connection(config_path)
    provider = onboarding.get_active_provider(config_path)
    if provider is not None and conn is not None:
        state.set_connected(conn.choice_id, provider)
    return state


def _launch_firefox_or_fallback(run, url: str) -> None:
    try:
        result = run([*FIREFOX_ARGV, url])
    except FileNotFoundError as exc:
        print(f"[webshell_cli] firefox not found ({exc}); falling back to text shell", file=sys.stderr)
        run(FALLBACK_ARGV)
        return

    if result.returncode != 0:
        print(
            f"[webshell_cli] firefox exited with code {result.returncode}; falling back to text shell",
            file=sys.stderr,
        )
        run(FALLBACK_ARGV)


def main(
    argv: list[str] | None = None,
    *,
    run=subprocess.run,
    port: int = DEFAULT_PORT,
    config_path: Path = onboarding.DEFAULT_CONFIG_PATH,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
) -> int:
    registry_path.parent.mkdir(parents=True, exist_ok=True)

    state = _initial_state(config_path)
    registry = AppRegistry(str(registry_path))
    server = build_server(state, registry, config_path=config_path, port=port)
    bound_port = server.server_address[1]

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    try:
        _launch_firefox_or_fallback(run, f"http://127.0.0.1:{bound_port}/")
    finally:
        server.shutdown()
        server.server_close()
        registry.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
