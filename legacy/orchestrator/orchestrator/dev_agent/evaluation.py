"""ROADMAP.md 2.6 -- "후보 평가 로직": functional fit, license, maintenance,
security signals for a single Candidate.

Deliberately conservative where the source data is ambiguous: a missing or
non-allowlisted license fails the automatic pass bar rather than being
assumed safe (doc separates "통과" from "플래그" -- a flag means "needs
human review", which isn't compatible with the fully-autonomous Path A
this feeds into). Same for vulnerabilities: any OSV hit fails, since
severity fields aren't consistent enough across ecosystems/sources in
OSV's schema to threshold on reliably here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from ..providers.base import LLMProvider
from ..task_spec import TaskSpec
from .candidates import Candidate
from .http_client import real_post_json

HttpPost = Callable[[str, dict], dict]

ALLOWED_LICENSES = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "0BSD", "Unlicense"}
FLAGGED_LICENSE_PREFIXES = ("GPL", "AGPL", "LGPL")

MAINTENANCE_MAX_AGE = timedelta(days=730)  # ~2 years
MAINTENANCE_MIN_POPULARITY = 50  # stars, or npm/crates download count

FUNCTIONAL_FIT_PASS_THRESHOLD = 0.6

_FIT_SCHEMA = {
    "type": "object",
    "required": ["score", "reasoning"],
    "properties": {
        "score": {"type": "number", "description": "0.0-1.0: does this candidate satisfy the requirement?"},
        "reasoning": {"type": "string"},
    },
}

_OSV_ECOSYSTEM = {"npm": "npm", "crates.io": "crates.io", "pypi": "PyPI"}


def license_verdict(license_id: str | None) -> str:
    if not license_id:
        return "unknown"
    if license_id in ALLOWED_LICENSES:
        return "allowed"
    if license_id.upper().startswith(FLAGGED_LICENSE_PREFIXES):
        return "flagged"
    return "unknown"


def maintenance_ok(candidate: Candidate, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    if candidate.popularity is not None and candidate.popularity >= MAINTENANCE_MIN_POPULARITY:
        return True
    if candidate.last_updated:
        try:
            updated = datetime.fromisoformat(candidate.last_updated.replace("Z", "+00:00"))
        except ValueError:
            return False
        return (now - updated) <= MAINTENANCE_MAX_AGE
    return False


def check_vulnerabilities(candidate: Candidate, http_post: HttpPost = real_post_json) -> list[dict]:
    ecosystem = _OSV_ECOSYSTEM.get(candidate.ecosystem)
    if ecosystem is None:  # e.g. "github" -- OSV queries by package+ecosystem, not repo
        return []
    resp = http_post("https://api.osv.dev/v1/query", {"package": {"name": candidate.name, "ecosystem": ecosystem}})
    return resp.get("vulns", [])


def judge_functional_fit(candidate: Candidate, task_spec: TaskSpec, provider: LLMProvider) -> float:
    data = provider.complete_json(
        f"Requirement: {task_spec.goal}\n"
        f"Candidate package: {candidate.name} ({candidate.ecosystem})\n"
        f"Candidate description: {candidate.description}\n"
        "Does this candidate's stated purpose plausibly satisfy the requirement?",
        schema=_FIT_SCHEMA,
    )
    return float(data["score"])


@dataclass
class CandidateEvaluation:
    candidate: Candidate
    license_verdict: str  # allowed | flagged | unknown
    maintenance_ok: bool
    vulnerabilities: list[dict]
    functional_fit_score: float

    @property
    def passes(self) -> bool:
        return (
            self.license_verdict == "allowed"
            and self.maintenance_ok
            and not self.vulnerabilities
            and self.functional_fit_score >= FUNCTIONAL_FIT_PASS_THRESHOLD
        )


def evaluate(
    candidate: Candidate,
    task_spec: TaskSpec,
    provider: LLMProvider,
    http_post: HttpPost = real_post_json,
) -> CandidateEvaluation:
    return CandidateEvaluation(
        candidate=candidate,
        license_verdict=license_verdict(candidate.license),
        maintenance_ok=maintenance_ok(candidate),
        vulnerabilities=check_vulnerabilities(candidate, http_post),
        functional_fit_score=judge_functional_fit(candidate, task_spec, provider),
    )
