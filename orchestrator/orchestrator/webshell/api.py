"""Pure request/response builders behind the HTTP routes.

Kept separate from `server.py`'s socket/threading plumbing so these can be
unit-tested directly (call a function, check the dict it returns) without
spinning up a real HTTP server.
"""

from __future__ import annotations

from ..llm import LLMBackedIntentAnalyzer
from ..providers.base import ProviderNotReady
from ..registry.db import AppRegistry
from ..state_machine import DevelopmentPending, Orchestrator, OrchestratorNotReady, OrchestratorTimeout
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


def prompt_payload(state: ConnectionState, registry: AppRegistry, text: str) -> dict:
    provider = state.provider
    if provider is None:
        return {"status": "error", "message": "LLM이 연결되지 않았습니다."}

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
