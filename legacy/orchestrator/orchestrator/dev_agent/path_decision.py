"""ROADMAP.md 2.6 -- 경로 A/B/C 결정.

경로 A (하이브리드): 통과한 후보가 있으면 그중 functional_fit_score가
가장 높은 것을 선택.
경로 C (사용자 확인): 통과 후보가 없고, 요구사항에 사용자 전용
자격증명/유료 API 키가 필요하다는 신호(estimated_permissions)가 있으면.
경로 B (순수 코드 생성): 그 외 전부 (통과 후보 없음, Path C 신호도 없음).
"""

from __future__ import annotations

from enum import Enum, auto

from ..task_spec import TaskSpec
from .evaluation import CandidateEvaluation

_CREDENTIAL_MARKERS = ("credential", "api_key", "api key", "paid")


class Path(Enum):
    HYBRID_INSTALL = auto()  # A
    CODE_GENERATION = auto()  # B
    ASK_USER = auto()  # C


def decide_path(
    evaluations: list[CandidateEvaluation], task_spec: TaskSpec
) -> tuple[Path, str, CandidateEvaluation | None]:
    passing = [e for e in evaluations if e.passes]
    if passing:
        best = max(passing, key=lambda e: e.functional_fit_score)
        return (
            Path.HYBRID_INSTALL,
            f"{best.candidate.name} ({best.candidate.ecosystem}) passed all checks "
            f"(fit={best.functional_fit_score:.2f})",
            best,
        )

    needs_credentials = any(
        marker in perm.lower() for perm in task_spec.estimated_permissions for marker in _CREDENTIAL_MARKERS
    )
    if needs_credentials:
        return Path.ASK_USER, "estimated_permissions indicates user-specific credentials are required", None

    if evaluations:
        reasons = ", ".join(
            f"{e.candidate.name}: license={e.license_verdict}, maintained={e.maintenance_ok}, "
            f"vulns={len(e.vulnerabilities)}, fit={e.functional_fit_score:.2f}"
            for e in evaluations
        )
        reason = f"no candidate passed all checks ({reasons})"
    else:
        reason = "no candidates found"
    return Path.CODE_GENERATION, reason, None
