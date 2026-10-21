"""The actual boot-time shell (ROADMAP.md 2.1 입력 레이어 + Phase 4's gate).

    [부팅] -> ... -> 여기
      -> 저장된 연결 있음? -> 프롬프트 입력 화면
      -> 없음 -> LLM 선택 -> 설치/로그인 -> 저장 -> 프롬프트 입력 화면

Console/text-based, kept as the headless-friendly path (SSH, recovery
console, or any environment with no display) -- `webshell_cli.py` is
what sway actually boots into now (a real graphical shell: prompt bar +
installed-app/LLM-connection icon dock in Firefox, per explicit user
feedback that a text menu doesn't count as "GUI"). Both share the exact
same connection logic (`onboarding.py`); only the UI on top differs.

Voice input (2.1's other half) isn't implemented -- no STT engine has been
chosen yet (ROADMAP.md 2.1). Text-only for now.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import onboarding
from .llm import LLMBackedIntentAnalyzer
from .onboarding import CHOICES, SavedConnection
from .providers.base import ExternalLoginRequired, ProviderNotReady
from .registry.db import AppRegistry
from .state_machine import DevelopmentPending, Orchestrator, OrchestratorNotReady, OrchestratorTimeout

DEFAULT_REGISTRY_PATH = Path.home() / ".local" / "share" / "oais" / "registry.db"


def _clear_screen() -> None:
    os.system("clear" if os.name != "nt" else "cls")  # noqa: S605 - fixed command, no user input


def _banner(title: str) -> None:
    _clear_screen()
    width = 60
    print("=" * width)
    print(title.center(width))
    print("=" * width)
    print()


def _prompt_provider_choice() -> onboarding.ProviderChoice:
    _banner("AI-OS 시작하기")
    print("사용할 AI를 선택하세요:\n")
    for i, choice in enumerate(CHOICES, start=1):
        print(f"  [{i}] {choice.label}")
    print()

    while True:
        raw = input("번호 입력: ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(CHOICES):
            return CHOICES[int(raw) - 1]
        print("잘못된 입력입니다. 다시 선택해주세요.\n")


def _connect_claude() -> onboarding.ClaudeCliProvider | None:
    print()
    print("Claude CLI를 설치하고 로그인 브라우저를 엽니다.")
    print("(로그인 완료까지 이 화면은 기다립니다)")
    print()
    input("계속하려면 Enter를 누르세요 (취소: Ctrl+C)... ")

    try:
        return onboarding.connect_claude_via_browser()
    except ExternalLoginRequired as exc:
        print(f"\n브라우저 로그인 실패: {exc}")
        return _connect_claude_via_token_fallback()


def _connect_claude_via_token_fallback() -> onboarding.ClaudeCliProvider | None:
    print()
    print("대신 다른 기기에서 만든 토큰으로 연결할 수 있습니다:")
    print("  1. 다른 기기(노트북/폰)에 Claude Code CLI 설치")
    print("  2. 그 기기 터미널에서 `claude setup-token` 실행")
    print("  3. 출력된 토큰을 복사해서 여기에 붙여넣기")
    print()
    token = input("토큰 붙여넣기 (취소: 빈 값): ").strip()
    if not token:
        return None

    print("\n연결 확인 중...")
    try:
        return onboarding.connect_claude_with_token(token)
    except ExternalLoginRequired as exc:
        print(f"\n연결 실패: {exc}")
        return None


def _connect_grok() -> onboarding.GrokCliProvider | None:
    print()
    print("Grok CLI를 설치하고 로그인 절차를 시작합니다.")
    print("URL과 코드가 나오면, 다른 기기의 브라우저에서 열어 로그인해주세요.")
    print("(로그인 완료까지 이 화면은 기다립니다)")
    print()
    input("계속하려면 Enter를 누르세요 (취소: Ctrl+C)... ")

    try:
        return onboarding.connect_grok()
    except ExternalLoginRequired as exc:
        print(f"\n연결 실패: {exc}")
        return None


def _connect_ollama() -> onboarding.OllamaProvider | None:
    model_id = input(f"\n모델 이름 (기본값 {onboarding.DEFAULT_OLLAMA_MODEL}): ").strip() or onboarding.DEFAULT_OLLAMA_MODEL
    print(f"\n{model_id} 설치/확인 중... (처음이면 다운로드 시간이 걸릴 수 있습니다)")
    try:
        return onboarding.connect_ollama(model_id)
    except ProviderNotReady as exc:
        print(f"\n연결 실패: {exc}")
        return None


def _connect_custom() -> onboarding.CustomCliProvider | None:
    print()
    cli_binary = input("CLI 실행 파일 이름 (예: mycli): ").strip()
    if not cli_binary:
        return None
    login_command = input(f"로그인 명령어 (예: {cli_binary} login): ").strip() or f"{cli_binary} login"
    install_raw = input("설치 명령어 (없으면 빈 값, 공백으로 구분, 예: npm install -g mycli): ").strip()
    install_argv = install_raw.split() if install_raw else None

    print("\n연결 확인 중...")
    try:
        return onboarding.connect_custom(f"custom-{cli_binary}", cli_binary, login_command, install_argv)
    except ExternalLoginRequired as exc:
        print(f"\n연결 실패: {exc}")
        return None


_CONNECTORS = {
    "claude": _connect_claude,
    "grok": _connect_grok,
    "ollama": _connect_ollama,
    "custom": _connect_custom,
}


def _run_connection_flow(config_path: Path):
    while True:
        choice = _prompt_provider_choice()
        provider = _CONNECTORS[choice.id]()
        if provider is not None:
            model_id = getattr(provider, "model_id", None)
            if choice.id == "custom":
                conn = SavedConnection(
                    choice_id="custom",
                    custom_cli_binary=provider.cli_binary,
                    custom_login_command=provider.login_command,
                    custom_install_argv=provider.install_argv,
                )
            else:
                conn = SavedConnection(choice_id=choice.id, model_id=model_id)
            onboarding.save_connection(conn, config_path)
            print(f"\n연결 완료: {choice.label}\n")
            input("계속하려면 Enter를 누르세요...")
            return provider
        print("\n다시 시도합니다.\n")
        input("계속하려면 Enter를 누르세요...")


def _prompt_loop(provider, registry_path: Path) -> None:
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry = AppRegistry(str(registry_path))
    orchestrator = Orchestrator(
        registry=registry,
        intent_analyzer=LLMBackedIntentAnalyzer(provider),
        dev_provider=provider,
    )

    _banner("AI-OS")
    print("무엇을 도와드릴까요? (종료: exit)\n")

    try:
        while True:
            try:
                raw_prompt = input("> ").strip()
            except EOFError:
                break
            if not raw_prompt:
                continue
            if raw_prompt.lower() in ("exit", "quit"):
                break

            try:
                result = orchestrator.process(raw_prompt)
            except DevelopmentPending as exc:
                dev = exc.development_result
                print(f"[개발 경로: {dev.path.name}] {dev.reason}")
                if dev.exec_manifest:
                    print(f"실행 매니페스트(아직 실행/검증 안 됨): {dev.exec_manifest}")
            except (OrchestratorNotReady, OrchestratorTimeout, ProviderNotReady) as exc:
                print(f"[{type(exc).__name__}] {exc}")
                continue

            if result.status == "needs_clarification":
                print("추가 정보가 필요합니다:")
                for q in result.clarification_questions:
                    print(f"  - {q}")
            else:
                print(result.summary)
            print()
    finally:
        registry.close()


def main(argv: list[str] | None = None) -> int:
    config_path = onboarding.DEFAULT_CONFIG_PATH
    registry_path = DEFAULT_REGISTRY_PATH

    provider = onboarding.get_active_provider(config_path)
    if provider is None:
        provider = _run_connection_flow(config_path)

    _prompt_loop(provider, registry_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
