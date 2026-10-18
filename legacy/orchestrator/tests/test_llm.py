import unittest

from orchestrator.llm import LLMBackedIntentAnalyzer
from orchestrator.providers.base import LLMProvider, ProviderStatus
from orchestrator.task_spec import TaskSpec


class _FakeProvider(LLMProvider):
    provider_id = "fake"

    def __init__(self, response: dict):
        self._response = response

    def status(self):
        return ProviderStatus.READY

    def ensure_ready(self):
        pass

    def complete_json(self, prompt, schema):
        assert "raw_prompt" in schema["properties"]
        return self._response


class TestLLMBackedIntentAnalyzer(unittest.TestCase):
    def test_analyze_converts_provider_response_into_task_spec(self):
        provider = _FakeProvider(
            {
                "goal": "translate the document",
                "capability_tags": ["translate", "document"],
                "needs_clarification": False,
            }
        )
        analyzer = LLMBackedIntentAnalyzer(provider)

        spec = analyzer.analyze("translate this doc")

        self.assertIsInstance(spec, TaskSpec)
        self.assertEqual(spec.goal, "translate the document")
        self.assertEqual(spec.raw_prompt, "translate this doc")

    def test_provider_can_set_raw_prompt_explicitly(self):
        provider = _FakeProvider({"goal": "x", "raw_prompt": "overridden", "needs_clarification": False})
        analyzer = LLMBackedIntentAnalyzer(provider)

        spec = analyzer.analyze("original")

        self.assertEqual(spec.raw_prompt, "overridden")


if __name__ == "__main__":
    unittest.main()
