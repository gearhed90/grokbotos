import unittest

from orchestrator.dev_agent.path_decision import Path as DevPath
from orchestrator.registry.db import AppRegistry
from orchestrator.state_machine import DevelopmentPending, Orchestrator, State
from orchestrator.task_spec import TaskSpec
from tests.fakes import SchemaRoutedProvider
from tests.test_state_machine import _FixedAnalyzer


def _empty_search(url, headers):
    if "registry.npmjs.org" in url:
        return {"objects": []}
    if "crates.io" in url:
        return {"crates": []}
    if "api.github.com" in url:
        return {"items": []}
    raise AssertionError(f"unexpected URL {url}")


def _pypi_not_found(url, headers):
    raise Exception("404")


class TestDevAgentWiredIntoStateMachine(unittest.TestCase):
    """ROADMAP.md 2.5/2.6 (dev_agent) reached through Orchestrator.process()
    instead of calling dev_agent.agent.develop() directly -- this is what
    scenario B (no registry match -> development) now actually does, up
    to the 2.7/2.8 boundary."""

    def setUp(self):
        self.registry = AppRegistry(":memory:")

    def tearDown(self):
        self.registry.close()

    def _fake_get(self, url, headers=None):
        if "pypi.org" in url:
            return _pypi_not_found(url, headers)
        return _empty_search(url, headers)

    def test_no_match_with_dev_provider_raises_development_pending(self):
        provider = SchemaRoutedProvider(
            {
                "work_items": {"work_items": ["x"], "search_keywords": ["zzz-nonexistent"]},
                "code": {"code": "print('x')", "entrypoint_command": "python3 main.py", "dependencies": []},
            }
        )
        analyzer = _FixedAnalyzer(
            TaskSpec(raw_prompt="do something new", goal="something new", capability_tags=["nonexistent"])
        )
        orchestrator = Orchestrator(
            self.registry,
            analyzer,
            dev_provider=provider,
            dev_http_get=self._fake_get,
            dev_http_post=lambda url, body: {"vulns": []},
        )

        with self.assertRaises(DevelopmentPending) as ctx:
            orchestrator.process("do something new")

        result = ctx.exception.development_result
        self.assertEqual(result.path, DevPath.CODE_GENERATION)
        self.assertIsNotNone(result.exec_manifest)

    def test_credential_signal_surfaces_as_needs_clarification(self):
        provider = SchemaRoutedProvider(
            {"work_items": {"work_items": [], "search_keywords": ["private-service"]}}
        )
        analyzer = _FixedAnalyzer(
            TaskSpec(
                raw_prompt="post to my private paid API",
                goal="post to my private paid API",
                capability_tags=["nonexistent"],
                estimated_permissions=["requires a paid API key"],
            )
        )
        orchestrator = Orchestrator(
            self.registry,
            analyzer,
            dev_provider=provider,
            dev_http_get=self._fake_get,
            dev_http_post=lambda url, body: {"vulns": []},
        )

        result = orchestrator.process("post to my private paid API")

        self.assertEqual(result.status, "needs_clarification")
        self.assertEqual(result.final_state, State.NEEDS_CLARIFICATION)
        self.assertTrue(result.clarification_questions)


if __name__ == "__main__":
    unittest.main()
