"""ROADMAP.md 2.5+2.6 entrypoint: `develop()` takes a TaskSpec that had no
registry match and produces either an exec_manifest (paths A/B) ready for
2.8 registration, or clarification questions (path C).

What this does NOT do: install anything, run anything, or test anything --
that's 2.7 (test/verify) and Phase 3 (sandbox), neither of which exist
yet. Every exec_manifest this produces points `sandbox_profile_id` at
"phase3-not-implemented" so nothing downstream can mistake it for
something safe to execute.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..providers.base import LLMProvider
from ..task_spec import TaskSpec
from . import candidates as candidates_mod
from . import planning
from .codegen import GeneratedCode, generate_from_scratch, generate_wrapper
from .evaluation import CandidateEvaluation, evaluate
from .http_client import real_get, real_post_json
from .path_decision import Path, decide_path
from .planning import DevelopmentPlan

SANDBOX_PROFILE_NOT_IMPLEMENTED = "phase3-not-implemented"


@dataclass
class DevelopmentResult:
    plan: DevelopmentPlan
    candidates_evaluated: list[CandidateEvaluation]
    path: Path
    reason: str
    creation_source: str | None = None  # "hybrid" | "generated" -- registry schema value, set for A/B
    generated_code: GeneratedCode | None = None
    exec_manifest: dict | None = None
    clarification_questions: list[str] = field(default_factory=list)


def develop(
    task_spec: TaskSpec,
    provider: LLMProvider,
    http_get=real_get,
    http_post=real_post_json,
) -> DevelopmentResult:
    dev_plan = planning.plan(task_spec, provider)
    query = " ".join(dev_plan.search_keywords) or task_spec.goal

    found = []
    found += candidates_mod.search_npm(query, http_get=http_get)
    found += candidates_mod.search_crates(query, http_get=http_get)
    found += candidates_mod.search_github(query, http_get=http_get)
    for keyword in dev_plan.search_keywords[:3]:
        pypi_hit = candidates_mod.lookup_pypi(keyword, http_get=http_get)
        if pypi_hit is not None:
            found.append(pypi_hit)

    evaluations = [evaluate(c, task_spec, provider, http_post=http_post) for c in found]
    path, reason, best = decide_path(evaluations, task_spec)

    if path is Path.HYBRID_INSTALL:
        code = generate_wrapper(best.candidate, task_spec, provider)
        return DevelopmentResult(
            plan=dev_plan,
            candidates_evaluated=evaluations,
            path=path,
            reason=reason,
            creation_source="hybrid",
            generated_code=code,
            exec_manifest=_build_exec_manifest(dev_plan, code),
        )

    if path is Path.CODE_GENERATION:
        code = generate_from_scratch(task_spec, provider)
        return DevelopmentResult(
            plan=dev_plan,
            candidates_evaluated=evaluations,
            path=path,
            reason=reason,
            creation_source="generated",
            generated_code=code,
            exec_manifest=_build_exec_manifest(dev_plan, code),
        )

    return DevelopmentResult(
        plan=dev_plan,
        candidates_evaluated=evaluations,
        path=path,
        reason=reason,
        clarification_questions=[
            "This task appears to need credentials or a paid API key only you can "
            f"provide (estimated_permissions={task_spec.estimated_permissions}). "
            "What should be used?"
        ],
    )


def _build_exec_manifest(dev_plan: DevelopmentPlan, code: GeneratedCode) -> dict:
    return {
        "entrypoint": code.entrypoint_command,
        "runtime": dev_plan.likely_runtime,
        "sandbox_profile_id": SANDBOX_PROFILE_NOT_IMPLEMENTED,
        "dependencies": code.dependencies,
    }
