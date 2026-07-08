"""LLM-generated code for Path A (thin wrapper around a chosen candidate)
and Path B (from-scratch implementation). Both ROADMAP.md 2.6 items.

Generating the code text is buildable now (just an LLM call). *Running* or
*testing* what comes out is not -- that needs Phase 3's sandbox, which is
why every caller of this module stores the result in an exec_manifest
with `sandbox_profile_id` pointing at a profile that doesn't exist yet
(see agent.py) instead of executing it.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..providers.base import LLMProvider
from ..task_spec import TaskSpec
from .candidates import Candidate

_CODEGEN_SCHEMA = {
    "type": "object",
    "required": ["code", "entrypoint_command", "dependencies"],
    "properties": {
        "code": {"type": "string"},
        "entrypoint_command": {"type": "string", "description": "How to run the generated code, e.g. 'python3 main.py'."},
        "dependencies": {"type": "array", "items": {"type": "string"}},
    },
}


@dataclass
class GeneratedCode:
    code: str
    entrypoint_command: str
    dependencies: list[str]


def generate_wrapper(candidate: Candidate, task_spec: TaskSpec, provider: LLMProvider) -> GeneratedCode:
    data = provider.complete_json(
        f"Write a minimal wrapper script that uses the '{candidate.name}' package "
        f"({candidate.ecosystem}) to accomplish: {task_spec.goal}\n"
        f"Input format: {task_spec.input_format}. Output format: {task_spec.output_format}.\n"
        "Keep it as thin as possible -- call the library, don't reimplement it.",
        schema=_CODEGEN_SCHEMA,
    )
    deps = list(dict.fromkeys([candidate.name, *data.get("dependencies", [])]))
    return GeneratedCode(code=data["code"], entrypoint_command=data["entrypoint_command"], dependencies=deps)


def generate_from_scratch(task_spec: TaskSpec, provider: LLMProvider) -> GeneratedCode:
    data = provider.complete_json(
        f"Write a self-contained implementation that accomplishes: {task_spec.goal}\n"
        f"Input format: {task_spec.input_format}. Output format: {task_spec.output_format}.\n"
        f"Constraints: {task_spec.constraints}",
        schema=_CODEGEN_SCHEMA,
    )
    return GeneratedCode(
        code=data["code"], entrypoint_command=data["entrypoint_command"], dependencies=data.get("dependencies", [])
    )
