"""Intent analysis (ROADMAP.md 2.2).

The connection *shape* is decided (docs/DECISIONS.md: auth-based cloud +
auto-installed local, see orchestrator/providers/). No concrete cloud
provider is wired up yet, and no routing policy for "하이브리드" (when to
use cloud vs. local) exists yet either. `IntentAnalyzer` is the interface
both a real implementation and the still-used `StubIntentAnalyzer`
(keyword-splitting placeholder) implement, so the rest of the pipeline
(registry matching, state machine branching) doesn't care which is
plugged in.

Do not mistake StubIntentAnalyzer for a real implementation -- it does not
understand the prompt, it just tokenizes it.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from pathlib import Path

from .providers.base import LLMProvider
from .task_spec import TaskSpec

_STOPWORDS = {
    "the", "a", "an", "to", "for", "of", "please", "이", "그", "저", "을",
    "를", "이것", "저것", "해줘", "해주세요", "좀",
}

_TASK_SPEC_SCHEMA = json.loads((Path(__file__).with_name("task_spec.schema.json")).read_text())


class IntentAnalyzer(ABC):
    @abstractmethod
    def analyze(self, raw_prompt: str) -> TaskSpec: ...


class StubIntentAnalyzer(IntentAnalyzer):
    """Placeholder: extracts lowercase word tokens as capability_tags and
    echoes the prompt as the goal. Never sets needs_clarification -- a real
    LLM-backed analyzer is what ROADMAP.md 2.2 actually calls for that
    clarification rule."""

    def analyze(self, raw_prompt: str) -> TaskSpec:
        tokens = re.findall(r"[\w가-힣]+", raw_prompt.lower())
        tags = [t for t in tokens if t not in _STOPWORDS and len(t) > 1]
        return TaskSpec(
            raw_prompt=raw_prompt,
            goal=raw_prompt.strip(),
            capability_tags=tags,
        )


class LLMBackedIntentAnalyzer(IntentAnalyzer):
    """Real implementation: asks `provider` to fill in task_spec.schema.json
    from the raw prompt. Requires `provider.ensure_ready()` to have already
    succeeded -- this class doesn't drive the auth/install flow itself,
    since the pipeline's caller (eventually the Phase 4 shell) is what
    should be showing the user "log in" / "downloading model" progress."""

    def __init__(self, provider: LLMProvider):
        self._provider = provider

    def analyze(self, raw_prompt: str) -> TaskSpec:
        data = self._provider.complete_json(raw_prompt, schema=_TASK_SPEC_SCHEMA)
        data.setdefault("raw_prompt", raw_prompt)
        return TaskSpec.from_dict(data)
