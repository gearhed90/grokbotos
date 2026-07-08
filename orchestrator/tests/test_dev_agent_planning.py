import unittest

from orchestrator.dev_agent.planning import plan
from orchestrator.task_spec import TaskSpec
from tests.fakes import SchemaRoutedProvider


class TestPlanning(unittest.TestCase):
    def test_plan_converts_provider_response(self):
        provider = SchemaRoutedProvider(
            {
                "work_items": {
                    "work_items": ["parse input", "extract text", "format output"],
                    "search_keywords": ["pdf", "text-extraction"],
                    "likely_runtime": "python3.12",
                }
            }
        )
        task_spec = TaskSpec(raw_prompt="extract text from pdf", goal="extract text from pdf")

        result = plan(task_spec, provider)

        self.assertEqual(result.work_items, ["parse input", "extract text", "format output"])
        self.assertEqual(result.search_keywords, ["pdf", "text-extraction"])
        self.assertEqual(result.likely_runtime, "python3.12")

    def test_plan_defaults_runtime_when_missing(self):
        provider = SchemaRoutedProvider({"work_items": {"work_items": [], "search_keywords": []}})
        task_spec = TaskSpec(raw_prompt="x", goal="x")

        result = plan(task_spec, provider)

        self.assertEqual(result.likely_runtime, "python3")


if __name__ == "__main__":
    unittest.main()
