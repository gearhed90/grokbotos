"""Closed-loop controller (ROADMAP.md "폐쇄루프 컨트롤러" + 2.1-2.9).

    RECEIVED -> INTENT_ANALYSIS -> REGISTRY_SEARCH
      -> EXECUTE_EXISTING -> DELIVER_RESULT
      -> PLAN -> DEVELOP -> TEST -> (REGISTER_AND_EXECUTE -> DELIVER_RESULT
                                      | RETRY_DEVELOP, up to max_retries)

PLAN/DEVELOP/TEST/REGISTER_AND_EXECUTE (ROADMAP.md 2.5-2.8) are not
implemented -- there is no development agent, test agent, or Phase 3
sandbox to call into yet. Reaching that branch raises OrchestratorNotReady
with a message naming which ROADMAP.md section is missing, rather than
faking success.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from .llm import IntentAnalyzer
from .registry.db import AppRecord, AppRegistry
from .registry.matcher import find_best_match
from .task_spec import TaskSpec

# ROADMAP.md 2.3 threshold policy
CONFIDENCE_EXECUTE = 0.85
CONFIDENCE_ADAPTER = 0.6


class State(Enum):
    RECEIVED = auto()
    INTENT_ANALYSIS = auto()
    REGISTRY_SEARCH = auto()
    EXECUTE_EXISTING = auto()
    NEEDS_CLARIFICATION = auto()
    PLAN = auto()
    DEVELOP = auto()
    TEST = auto()
    REGISTER_AND_EXECUTE = auto()
    RETRY_DEVELOP = auto()
    DELIVER_RESULT = auto()
    FAILED = auto()


class OrchestratorNotReady(Exception):
    """Raised when the pipeline reaches a stage that ROADMAP.md describes
    but this prototype hasn't implemented yet."""


class OrchestratorTimeout(Exception):
    """Raised when a single process() call exceeds its wall-clock budget
    (ROADMAP.md 폐쇄루프 컨트롤러: '각 상태 전이에 타임아웃 ... 설정')."""


@dataclass
class ResultEnvelope:
    """Standard result format (ROADMAP.md 2.9), shared by the
    EXECUTE_EXISTING and REGISTER_AND_EXECUTE paths."""

    status: str  # success | failed | needs_clarification
    kind: str = "text"  # text | file | structured
    summary: str = ""
    payload: Any = None
    source_app_id: str | None = None
    final_state: State = State.RECEIVED
    clarification_questions: list[str] = field(default_factory=list)


class Orchestrator:
    def __init__(
        self,
        registry: AppRegistry,
        intent_analyzer: IntentAnalyzer,
        max_retries: int = 3,
        timeout_seconds: float = 30.0,
    ):
        self._registry = registry
        self._intent_analyzer = intent_analyzer
        self._max_retries = max_retries
        self._timeout_seconds = timeout_seconds

    def process(self, raw_prompt: str) -> ResultEnvelope:
        deadline = time.monotonic() + self._timeout_seconds
        state = State.RECEIVED

        state = State.INTENT_ANALYSIS
        self._check_deadline(deadline, state)
        task_spec = self._intent_analyzer.analyze(raw_prompt)

        if task_spec.needs_clarification:
            return ResultEnvelope(
                status="needs_clarification",
                summary="Need more information before proceeding.",
                final_state=State.NEEDS_CLARIFICATION,
                clarification_questions=task_spec.clarification_questions,
            )

        state = State.REGISTRY_SEARCH
        self._check_deadline(deadline, state)
        match = find_best_match(self._registry, task_spec)

        if match.app is not None and match.confidence >= CONFIDENCE_EXECUTE:
            return self._execute_existing(match.app, deadline)

        if match.app is not None and match.confidence >= CONFIDENCE_ADAPTER:
            raise OrchestratorNotReady(
                "0.6-0.85 confidence adapter path (ROADMAP.md 2.3: '어댑터 "
                "생성 경로') is out of scope for the MVP prototype -- "
                "explicitly deferred to a separate track in the roadmap."
            )

        raise OrchestratorNotReady(
            "No confident registry match; would proceed to PLAN -> DEVELOP "
            "-> TEST -> REGISTER (ROADMAP.md 2.5-2.8), none of which are "
            "implemented yet (no planning/dev/test agent, no Phase 3 "
            f"sandbox). max_retries={self._max_retries} is reserved for "
            "that loop once it exists."
        )

    def _execute_existing(self, app: AppRecord, deadline: float) -> ResultEnvelope:
        """ROADMAP.md 2.4. Stubbed: no Phase 3 sandbox exists yet to
        actually invoke `app.exec_manifest` in, so this fakes a successful
        run and records usage, matching the shape a real execution would
        return via 2.9's shared result envelope."""
        self._check_deadline(deadline, State.EXECUTE_EXISTING)
        self._registry.record_usage(
            app.app_id, used_at=_now_iso(), success=True
        )
        return ResultEnvelope(
            status="success",
            kind="text",
            summary=f"[stub] would run {app.name} ({app.exec_manifest.get('entrypoint', '?')})",
            source_app_id=app.app_id,
            final_state=State.DELIVER_RESULT,
        )

    @staticmethod
    def _check_deadline(deadline: float, state: State) -> None:
        if time.monotonic() > deadline:
            raise OrchestratorTimeout(f"Timed out during {state.name}")


def _now_iso() -> str:
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).isoformat()
