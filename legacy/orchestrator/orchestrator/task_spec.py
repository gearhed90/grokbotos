"""Task Spec: the structured form every user request is converted into
before it reaches registry search / planning / development.

See ROADMAP.md 2.2 -- "사용자 요청 -> 구조화된 Task Spec(목표, 입력/출력
형식, 제약조건, 필요 권한 추정)으로 변환". The JSON Schema in
task_spec.schema.json alongside this file is the contract an LLM-based
intent analyzer (not implemented yet) would be asked to fill in.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field


@dataclass
class TaskSpec:
    raw_prompt: str
    goal: str
    input_format: str = "text"
    output_format: str = "text"
    constraints: list[str] = field(default_factory=list)
    estimated_permissions: list[str] = field(default_factory=list)
    capability_tags: list[str] = field(default_factory=list)

    # ROADMAP.md 2.2: "모호한 요청에 대한 재질문 규칙" -- if the analyzer
    # couldn't confidently fill in `goal`, it must flag this instead of
    # guessing, and the pipeline halts at INTENT_ANALYSIS until answered.
    needs_clarification: bool = False
    clarification_questions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> "TaskSpec":
        return cls(**data)
