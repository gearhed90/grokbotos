"""ROADMAP.md 2.5 -- decompose a TaskSpec into a development plan.

A single LLMProvider.complete_json() call. Resource/package estimation is
explicitly deferred to 2.6's candidate evaluation per ROADMAP.md ("상세
판단 기준은 2.6 의사결정 트리에서 처리"), so this stays deliberately thin.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..providers.base import LLMProvider
from ..task_spec import TaskSpec

_PLAN_SCHEMA = {
    "type": "object",
    "required": ["work_items", "search_keywords"],
    "properties": {
        "work_items": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Ordered, concrete implementation steps.",
        },
        "search_keywords": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Keywords to search package registries with (2.6).",
        },
        "likely_runtime": {
            "type": "string",
            "description": "Best-guess runtime for exec_manifest, e.g. 'python3.12', 'node20'.",
        },
    },
}


@dataclass
class DevelopmentPlan:
    work_items: list[str]
    search_keywords: list[str]
    likely_runtime: str = "python3"


def plan(task_spec: TaskSpec, provider: LLMProvider) -> DevelopmentPlan:
    data = provider.complete_json(
        "Break this task down into a development plan.\n"
        f"Goal: {task_spec.goal}\n"
        f"Input format: {task_spec.input_format}\n"
        f"Output format: {task_spec.output_format}\n"
        f"Constraints: {task_spec.constraints}\n"
        f"Known capability tags: {task_spec.capability_tags}",
        schema=_PLAN_SCHEMA,
    )
    return DevelopmentPlan(
        work_items=data["work_items"],
        search_keywords=data["search_keywords"],
        likely_runtime=data.get("likely_runtime", "python3"),
    )
