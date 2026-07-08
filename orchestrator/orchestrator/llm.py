"""Intent analysis (ROADMAP.md 2.2).

No LLM provider decision has been made yet (cloud API / local model /
hybrid -- see the open question in docs/ROADMAP.md). `IntentAnalyzer` is
the interface a real implementation plugs into; `StubIntentAnalyzer` is a
keyword-splitting placeholder so the rest of the pipeline (registry
matching, state machine branching) can be built and tested without
blocking on that decision.

Do not mistake StubIntentAnalyzer for a real implementation -- it does not
understand the prompt, it just tokenizes it.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod

from .task_spec import TaskSpec

_STOPWORDS = {
    "the", "a", "an", "to", "for", "of", "please", "이", "그", "저", "을",
    "를", "이것", "저것", "해줘", "해주세요", "좀",
}


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
