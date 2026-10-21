import unittest

from orchestrator.llm import IntentAnalyzer
from orchestrator.registry.db import AppRecord, AppRegistry
from orchestrator.state_machine import (
    Orchestrator,
    OrchestratorNotReady,
    OrchestratorTimeout,
    State,
)
from orchestrator.task_spec import TaskSpec


class _FixedAnalyzer(IntentAnalyzer):
    """Test double so state-machine branching can be tested independently
    of the (stub, keyword-based) real intent analyzer."""

    def __init__(self, task_spec: TaskSpec):
        self._task_spec = task_spec

    def analyze(self, raw_prompt: str) -> TaskSpec:
        return self._task_spec


def _register_app(registry, app_id, tags):
    registry.register(
        AppRecord(
            app_id=app_id,
            name=app_id,
            description="test app",
            capability_tags=tags,
            input_schema={"type": "object"},
            output_schema={"type": "string"},
            exec_manifest={"entrypoint": "true", "runtime": "shell", "sandbox_profile_id": "none", "dependencies": []},
            creation_source="generated",
            version="0.1.0",
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )
    )


class TestOrchestratorScenarios(unittest.TestCase):
    def setUp(self):
        self.registry = AppRegistry(":memory:")

    def tearDown(self):
        self.registry.close()

    def test_scenario_a_full_tag_overlap_executes_existing_app(self):
        """Analog of ROADMAP.md Phase 2 End-to-End scenario A: a
        pre-registered app matching the request is executed directly,
        no development involved."""
        _register_app(self.registry, "app.existing", tags=["translate", "text"])
        analyzer = _FixedAnalyzer(
            TaskSpec(raw_prompt="translate this", goal="translate", capability_tags=["translate", "text"])
        )
        orchestrator = Orchestrator(self.registry, analyzer)

        result = orchestrator.process("translate this")

        self.assertEqual(result.status, "success")
        self.assertEqual(result.final_state, State.DELIVER_RESULT)
        self.assertEqual(result.source_app_id, "app.existing")

    def test_scenario_c_repeat_request_reuses_same_app_without_redevelopment(self):
        """Analog of scenario C: process the same request twice; the
        second call must resolve via REGISTRY_SEARCH, not raise
        OrchestratorNotReady (which is what a 'would need development'
        path raises here)."""
        _register_app(self.registry, "app.existing", tags=["translate"])
        analyzer = _FixedAnalyzer(
            TaskSpec(raw_prompt="translate this", goal="translate", capability_tags=["translate"])
        )
        orchestrator = Orchestrator(self.registry, analyzer)

        first = orchestrator.process("translate this")
        second = orchestrator.process("translate this")

        self.assertEqual(first.status, "success")
        self.assertEqual(second.status, "success")

    def test_no_registry_match_without_dev_provider_raises_not_ready(self):
        """Analog of scenario B's first half: nothing in the registry, and
        with no dev_provider configured, the pipeline must say so
        explicitly rather than fabricate a result. (With a dev_provider
        configured, see test_dev_agent_wiring.py for what happens instead.)"""
        analyzer = _FixedAnalyzer(
            TaskSpec(raw_prompt="do something new", goal="something new", capability_tags=["nonexistent"])
        )
        orchestrator = Orchestrator(self.registry, analyzer)

        with self.assertRaises(OrchestratorNotReady) as ctx:
            orchestrator.process("do something new")

        self.assertIn("dev_provider", str(ctx.exception))

    def test_partial_match_in_adapter_band_raises_not_ready(self):
        # 2 of 3 query tags overlap -> confidence 0.667, inside the
        # 0.6-0.85 adapter band (ROADMAP.md 2.3 threshold policy).
        _register_app(self.registry, "app.partial", tags=["translate", "summarize", "pdf"])
        analyzer = _FixedAnalyzer(
            TaskSpec(raw_prompt="translate and summarize this", goal="translate+summarize",
                     capability_tags=["translate", "summarize", "ocr"])
        )
        orchestrator = Orchestrator(self.registry, analyzer)

        with self.assertRaises(OrchestratorNotReady) as ctx:
            orchestrator.process("ocr this pdf")

        self.assertIn("adapter", str(ctx.exception).lower())

    def test_needs_clarification_short_circuits_before_registry_search(self):
        analyzer = _FixedAnalyzer(
            TaskSpec(
                raw_prompt="do the thing",
                goal="",
                needs_clarification=True,
                clarification_questions=["Which thing?"],
            )
        )
        orchestrator = Orchestrator(self.registry, analyzer)

        result = orchestrator.process("do the thing")

        self.assertEqual(result.status, "needs_clarification")
        self.assertEqual(result.clarification_questions, ["Which thing?"])

    def test_expired_deadline_raises_timeout(self):
        analyzer = _FixedAnalyzer(TaskSpec(raw_prompt="x", goal="x", capability_tags=["x"]))
        orchestrator = Orchestrator(self.registry, analyzer, timeout_seconds=-1)

        with self.assertRaises(OrchestratorTimeout):
            orchestrator.process("x")


if __name__ == "__main__":
    unittest.main()
