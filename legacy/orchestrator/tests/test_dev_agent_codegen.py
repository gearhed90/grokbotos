import unittest

from orchestrator.dev_agent.candidates import Candidate
from orchestrator.dev_agent.codegen import generate_from_scratch, generate_wrapper
from orchestrator.task_spec import TaskSpec
from tests.fakes import SchemaRoutedProvider


class TestGenerateWrapper(unittest.TestCase):
    def test_dedupes_candidate_name_into_dependencies(self):
        provider = SchemaRoutedProvider(
            {"code": {"code": "import pypdf", "entrypoint_command": "python3 main.py", "dependencies": ["pypdf"]}}
        )
        candidate = Candidate(ecosystem="pypi", name="pypdf", description="", license="MIT", url="https://x")
        task_spec = TaskSpec(raw_prompt="x", goal="extract text from pdf")

        result = generate_wrapper(candidate, task_spec, provider)

        self.assertEqual(result.dependencies, ["pypdf"])  # deduped, not ["pypdf", "pypdf"]
        self.assertEqual(result.entrypoint_command, "python3 main.py")


class TestGenerateFromScratch(unittest.TestCase):
    def test_returns_generated_code(self):
        provider = SchemaRoutedProvider(
            {"code": {"code": "print('hi')", "entrypoint_command": "python3 main.py", "dependencies": []}}
        )
        task_spec = TaskSpec(raw_prompt="x", goal="say hi")

        result = generate_from_scratch(task_spec, provider)

        self.assertEqual(result.code, "print('hi')")


if __name__ == "__main__":
    unittest.main()
