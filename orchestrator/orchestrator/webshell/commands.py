"""Slash-command router -- the core of the redesigned shell.

Every icon/tile in the UI does its job by submitting one of these through
the exact same `/api/prompt` path a manually typed prompt uses. There is
no separate per-icon code path: `/llm claude` typed by hand and the
"Claude 연결" tile clicked by mouse produce an identical request. `api.py`
routes any text starting with "/" here; anything else goes to the real
`Orchestrator`.
"""

from __future__ import annotations

import platform
import subprocess
import threading
from pathlib import Path

from .. import onboarding
from .connect import run_connect, run_connect_token
from .state import ConnectionState

DEFAULT_TERMINAL_ARGV = ["foot"]

HELP_TEXT = "\n".join(
    [
        "사용 가능한 명령:",
        "  /llm                          -- 사용 가능한 LLM 목록 보기",
        "  /llm <claude|grok|ollama>     -- 해당 LLM에 연결",
        "  /llm custom <cli이름> [로그인명령...]  -- 커스텀 CLI 기반 LLM 연결",
        "  /token claude <토큰>          -- 브라우저 로그인 실패 시 토큰으로 연결",
        "  /system                       -- 현재 연결 상태 요약",
        "  /system network                -- 네트워크 인터페이스 상태",
        "  /system info                    -- OS/하드웨어 정보",
        "  /cli                           -- 새 터미널 창 열기",
        "  /help                          -- 이 도움말",
    ]
)


def dispatch(
    text: str,
    *,
    state: ConnectionState,
    registry,
    config_path: Path,
    run=subprocess.run,
    popen=subprocess.Popen,
    connectors: dict | None = None,
    token_connector=None,
) -> dict:
    parts = text.strip().split()
    name = parts[0].lower()
    args = parts[1:]

    if name == "/help":
        return {"status": "success", "message": HELP_TEXT}
    if name == "/llm":
        return _cmd_llm(args, state=state, config_path=config_path, connectors=connectors)
    if name == "/token":
        return _cmd_token(args, state=state, config_path=config_path, token_connector=token_connector)
    if name == "/system":
        return _cmd_system(args, state=state, registry=registry, run=run)
    if name == "/cli":
        return _cmd_cli(popen=popen)

    return {
        "status": "error",
        "message": f"알 수 없는 명령입니다: {name}. /help로 사용 가능한 명령을 확인하세요.",
    }


def _cmd_llm(args: list[str], *, state: ConnectionState, config_path: Path, connectors: dict | None) -> dict:
    if not args:
        lines = [f"  {c.id:<8} {c.label}" for c in onboarding.CHOICES]
        return {"status": "success", "message": "/llm <id> 로 연결하세요:\n" + "\n".join(lines)}

    choice_id = args[0].lower()
    valid_ids = {c.id for c in onboarding.CHOICES}
    if choice_id not in valid_ids:
        return {"status": "error", "message": f"알 수 없는 LLM입니다: {choice_id}. /llm 으로 목록을 확인하세요."}

    cli_binary = None
    login_command = None
    if choice_id == "custom":
        if not args[1:]:
            return {
                "status": "error",
                "message": "사용법: /llm custom <cli실행파일> [로그인명령...] (예: /llm custom mycli mycli login)",
            }
        cli_binary = args[1]
        login_command = " ".join(args[2:]) if len(args) > 2 else f"{cli_binary} login"

    threading.Thread(
        target=run_connect,
        kwargs=dict(
            choice_id=choice_id,
            state=state,
            config_path=config_path,
            cli_binary=cli_binary,
            login_command=login_command,
            connectors=connectors,
        ),
        daemon=True,
    ).start()
    return {
        "status": "connecting",
        "message": f"{choice_id} 연결을 시작합니다. 브라우저 로그인 창이 뜨면 완료해주세요.",
    }


def _cmd_token(args: list[str], *, state: ConnectionState, config_path: Path, token_connector) -> dict:
    if len(args) < 2 or args[0].lower() != "claude":
        return {"status": "error", "message": "사용법: /token claude <토큰>"}
    token = args[1]
    threading.Thread(
        target=run_connect_token,
        kwargs=dict(
            choice_id="claude", token=token, state=state, config_path=config_path, token_connector=token_connector
        ),
        daemon=True,
    ).start()
    return {"status": "connecting", "message": "토큰 확인 중..."}


def _cmd_system(args: list[str], *, state: ConnectionState, registry, run) -> dict:
    sub = args[0].lower() if args else None

    if sub is None:
        snap = state.snapshot()
        provider_line = f"연결된 LLM: {snap['choice_id']}" if snap["connected"] else "연결된 LLM: 없음"
        app_count = len(registry.list_all())
        return {
            "status": "success",
            "message": "\n".join(
                [
                    provider_line,
                    f"등록된 프로그램: {app_count}개",
                    "네트워크 상태는 /system network, OS 정보는 /system info",
                ]
            ),
        }

    if sub == "network":
        try:
            result = run(["nmcli", "device", "status"], capture_output=True, text=True, timeout=10)
        except FileNotFoundError:
            return {"status": "error", "message": "nmcli를 찾을 수 없습니다."}
        if result.returncode != 0:
            return {"status": "error", "message": f"nmcli 실행 실패: {result.stderr.strip()}"}
        return {"status": "success", "message": result.stdout.strip()}

    if sub == "info":
        pretty_name = _read_pretty_name()
        return {
            "status": "success",
            "message": f"{pretty_name}\n{platform.system()} {platform.release()} ({platform.machine()})",
        }

    return {"status": "error", "message": f"알 수 없는 /system 하위 명령입니다: {sub}"}


def _read_pretty_name() -> str:
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip('"')
    except OSError:
        pass
    return "AI-OS"


def _cmd_cli(*, popen) -> dict:
    try:
        popen(DEFAULT_TERMINAL_ARGV)
    except FileNotFoundError:
        return {"status": "error", "message": "터미널(foot)을 찾을 수 없습니다."}
    return {"status": "success", "message": "새 터미널 창을 엽니다."}
