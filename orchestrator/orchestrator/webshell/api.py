"""Pure request/response builders behind the HTTP routes.

Kept separate from `server.py`'s socket/threading plumbing so these can be
unit-tested directly (call a function, check the dict it returns) without
spinning up a real HTTP server.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .. import onboarding
from ..llm import LLMBackedIntentAnalyzer
from ..providers.base import ProviderNotReady
from ..registry.db import AppRegistry
from ..state_machine import DevelopmentPending, Orchestrator, OrchestratorNotReady, OrchestratorTimeout
from . import commands
from .state import ConnectionState


def status_payload(state: ConnectionState) -> dict:
    return state.snapshot()


def apps_payload(registry: AppRegistry) -> dict:
    return {
        "apps": [
            {"app_id": app.app_id, "name": app.name, "description": app.description}
            for app in registry.list_all()
        ]
    }


def prompt_payload(
    state: ConnectionState,
    registry: AppRegistry,
    text: str,
    *,
    config_path: Path = onboarding.DEFAULT_CONFIG_PATH,
    run=subprocess.run,
    popen=subprocess.Popen,
    connectors: dict | None = None,
) -> dict:
    """Every tile in the UI submits through this same function -- a
    "/llm claude" click and a hand-typed "/llm claude" are identical
    requests by the time they get here. Slash-prefixed text is a
    built-in command (commands.py); anything else goes to the real
    Orchestrator."""
    text = text.strip()
    if text.startswith("/"):
        return commands.dispatch(
            text, state=state, registry=registry, config_path=config_path, run=run, popen=popen, connectors=connectors
        )

    provider = state.provider
    if provider is None:
        return {
            "status": "error",
            "message": "LLM이 연결되지 않았습니다. /llm 으로 연결하거나 /help 를 입력하세요.",
        }

    orchestrator = Orchestrator(
        registry=registry,
        intent_analyzer=LLMBackedIntentAnalyzer(provider),
        dev_provider=provider,
    )
    try:
        result = orchestrator.process(text)
    except DevelopmentPending as exc:
        dev = exc.development_result
        return {
            "status": "development_pending",
            "message": f"[개발 경로: {dev.path.name}] {dev.reason}",
            "exec_manifest": dev.exec_manifest,
        }
    except (OrchestratorNotReady, OrchestratorTimeout, ProviderNotReady) as exc:
        return {"status": "error", "message": str(exc)}

    if result.status == "needs_clarification":
        return {"status": "needs_clarification", "questions": result.clarification_questions}
    return {"status": "success", "message": result.summary}
