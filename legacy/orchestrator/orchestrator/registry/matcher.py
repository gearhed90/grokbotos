"""Tier-1 registry matching (ROADMAP.md 2.3).

Only the capability_tags pre-filter is implemented. Tiers 2 (embedding
similarity) and 3 (LLM re-verification) are not implemented -- see
orchestrator/README.md for why. Confidence here is a coarse proxy
(tag-overlap ratio), NOT the calibrated score ROADMAP.md's threshold
policy (>=0.85 direct execute / 0.6-0.85 adapter / <0.6 develop) assumes.
It's wired up so the state machine's branching logic is correct now and
only the scoring function needs to change once tiers 2-3 exist.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..task_spec import TaskSpec
from .db import AppRecord, AppRegistry


@dataclass
class MatchResult:
    app: AppRecord | None
    confidence: float  # 0.0-1.0, see module docstring caveat


def find_best_match(registry: AppRegistry, task_spec: TaskSpec) -> MatchResult:
    candidates = registry.find_by_tags(task_spec.capability_tags)
    if not candidates:
        return MatchResult(app=None, confidence=0.0)

    best = candidates[0]
    tag_set = set(task_spec.capability_tags)
    overlap = len(tag_set & set(best.capability_tags))
    confidence = overlap / len(tag_set) if tag_set else 0.0
    return MatchResult(app=best, confidence=confidence)
