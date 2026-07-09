"""Closed-loop controller (ROADMAP.md "폐쇄루프 컨트롤러" + 2.1-2.9).

    RECEIVED -> INTENT_ANALYSIS -> REGISTRY_SEARCH
      -> EXECUTE_EXISTING -> DELIVER_RESULT
      -> PLAN -> DEVELOP -> TEST -> (REGISTER_AND_EXECUTE -> DELIVER_RESULT
                                      | RETRY_DEVELOP, up to max_retries)

PLAN/DEVELOP (ROADMAP.md 2.5-2.6, `dev_agent/`) are wired in below, gated
on an `LLMProvider` being supplied -- without one, this behaves as before.
TEST/REGISTER_AND_EXECUTE (2.7-2.8) still aren't implemented -- there's no
test agent, no registration pipeline, and no Phase 3 sandbox to actually
run generated code in to verify it. Reaching that point raises
`DevelopmentPending` carrying the `DevelopmentResult` (candidates
evaluated, chosen path, exec_manifest) for inspection, instead of
registering/executing something nothing has verified.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from .dev_agent.agent import develop
from .dev_agent.http_client import real_get, real_post_json
from .dev_agent.path_decision import Path as DevPath
from .llm import IntentAnalyzer
from .providers.base import LLMProvider
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


class DevelopmentPending(OrchestratorNotReady):
    """PLAN+DEVELOP (2.5/2.6) ran and produced a candidate exec_manifest,
    but TEST (2.7) and REGISTER (2.8) don't exist yet to verify and
    persist it -- so it's surfaced here instead of being silently
    registered/executed unverified. `.development_result` carries what
    would have been registered (candidates evaluated, chosen path,
    generated code, exec_manifest) for inspection."""

    def __init__(self, development_result):
        self.development_result = development_result
        super().__init__(
            f"Developed via path {development_result.path.name} "
            f"({development_result.reason}) but can't verify or register it "
            "yet -- ROADMAP.md 2.7 (test/verify) and 2.8 (register) aren't "
            "implemented. See .development_result for what would have been "
            "registered."
        )


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
        dev_provider: LLMProvider | None = None,
        dev_http_get=real_get,
        dev_http_post=real_post_json,
        max_retries: int = 3,
        timeout_seconds: float = 30.0,
    ):
        self._registry = registry
        self._intent_analyzer = intent_analyzer
        self._dev_provider = dev_provider
        self._dev_http_get = dev_http_get
        self._dev_http_post = dev_http_post
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

        if self._dev_provider is None:
            raise OrchestratorNotReady(
                "No confident registry match, and no LLM provider configured "
                "for development -- pass dev_provider= to Orchestrator to "
                "run PLAN -> DEVELOP (ROADMAP.md 2.5-2.6, implemented in "
                "dev_agent/). TEST -> REGISTER (2.7-2.8) still aren't "
                f"implemented either way. max_retries={self._max_retries} is "
                "reserved for the retry-on-test-failure loop once 2.7 exists."
            )

        state = State.PLAN
        self._check_deadline(deadline, state)
        dev_result = develop(
            task_spec,
            self._dev_provider,
            http_get=self._dev_http_get,
            http_post=self._dev_http_post,
        )

        state = State.DEVELOP
        self._check_deadline(deadline, state)
        if dev_result.path is DevPath.ASK_USER:
            return ResultEnvelope(
                status="needs_clarification",
                summary="Need more information before development can proceed.",
                final_state=State.NEEDS_CLARIFICATION,
                clarification_questions=dev_result.clarification_questions,
            )

        raise DevelopmentPending(dev_result)

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
