import unittest

from orchestrator.dev_agent.agent import SANDBOX_PROFILE_NOT_IMPLEMENTED, develop
from orchestrator.dev_agent.path_decision import Path
from orchestrator.task_spec import TaskSpec
from tests.fakes import SchemaRoutedProvider


def _empty_search_response(url, headers):
    if "registry.npmjs.org" in url:
        return {"objects": []}
    if "crates.io" in url:
        return {"crates": []}
    if "api.github.com" in url:
        return {"items": []}
    raise AssertionError(f"unexpected URL {url}")


class TestDevelopPathA(unittest.TestCase):
    def test_passing_npm_candidate_takes_hybrid_install_path(self):
        def fake_get(url, headers):
            if "registry.npmjs.org" in url:
                return {
                    "objects": [
                        {
                            "package": {
                                "name": "pdf-lib",
                                "description": "Create and modify PDFs",
                                "license": "MIT",
                                "date": "2026-01-01T00:00:00.000Z",
                                "links": {"npm": "https://www.npmjs.com/package/pdf-lib"},
                            }
                        }
                    ]
                }
            if "crates.io" in url:
                return {"crates": []}
            if "api.github.com" in url:
                return {"items": []}
            if "pypi.org" in url:
                raise Exception("404")
            raise AssertionError(url)

        def fake_post(url, body):
            return {"vulns": []}

        provider = SchemaRoutedProvider(
            {
                "work_items": {
                    "work_items": ["parse pdf"],
                    "search_keywords": ["pdf-lib"],
                    "likely_runtime": "node20",
                },
                "score": {"score": 0.9, "reasoning": "matches"},
                "code": {"code": "const lib = require('pdf-lib')", "entrypoint_command": "node main.js", "dependencies": []},
            }
        )
        task_spec = TaskSpec(raw_prompt="edit a pdf", goal="edit a pdf")

        result = develop(task_spec, provider, http_get=fake_get, http_post=fake_post)

        self.assertEqual(result.path, Path.HYBRID_INSTALL)
        self.assertEqual(result.creation_source, "hybrid")
        self.assertEqual(result.exec_manifest["runtime"], "node20")
        self.assertEqual(result.exec_manifest["sandbox_profile_id"], SANDBOX_PROFILE_NOT_IMPLEMENTED)
        self.assertIn("pdf-lib", result.exec_manifest["dependencies"])
        self.assertEqual(result.clarification_questions, [])


class TestDevelopPathB(unittest.TestCase):
    def test_no_candidates_found_generates_code(self):
        def fake_get(url, headers):
            if "pypi.org" in url:
                raise Exception("404")
            return _empty_search_response(url, headers)

        provider = SchemaRoutedProvider(
            {
                "work_items": {"work_items": ["do the thing"], "search_keywords": ["zzz-nonexistent-package"]},
                "code": {"code": "print('generated')", "entrypoint_command": "python3 main.py", "dependencies": []},
            }
        )
        task_spec = TaskSpec(raw_prompt="do something obscure", goal="do something obscure")

        result = develop(task_spec, provider, http_get=fake_get, http_post=lambda url, body: {"vulns": []})

        self.assertEqual(result.path, Path.CODE_GENERATION)
        self.assertEqual(result.creation_source, "generated")
        self.assertEqual(result.exec_manifest["sandbox_profile_id"], SANDBOX_PROFILE_NOT_IMPLEMENTED)


class TestDevelopPathC(unittest.TestCase):
    def test_credential_signal_asks_user_instead_of_generating_code(self):
        def fake_get(url, headers):
            if "pypi.org" in url:
                raise Exception("404")
            return _empty_search_response(url, headers)

        provider = SchemaRoutedProvider(
            {"work_items": {"work_items": [], "search_keywords": ["private-service"]}}
        )
        task_spec = TaskSpec(
            raw_prompt="post to my private paid API",
            goal="post to my private paid API",
            estimated_permissions=["requires a paid API key"],
        )

        result = develop(task_spec, provider, http_get=fake_get, http_post=lambda url, body: {"vulns": []})

        self.assertEqual(result.path, Path.ASK_USER)
        self.assertIsNone(result.exec_manifest)
        self.assertTrue(result.clarification_questions)


if __name__ == "__main__":
    unittest.main()
