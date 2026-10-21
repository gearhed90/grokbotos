import unittest

from orchestrator.dev_agent.candidates import Candidate
from orchestrator.dev_agent.evaluation import CandidateEvaluation
from orchestrator.dev_agent.path_decision import Path, decide_path
from orchestrator.task_spec import TaskSpec


def _eval(passes, name="pkg", fit=0.9, license_verdict="allowed", maintenance_ok=True, vulns=None):
    candidate = Candidate(ecosystem="npm", name=name, description="", license="MIT", url="https://x")
    e = CandidateEvaluation(
        candidate=candidate,
        license_verdict=license_verdict,
        maintenance_ok=maintenance_ok,
        vulnerabilities=vulns or [],
        functional_fit_score=fit,
    )
    assert e.passes == passes
    return e


class TestDecidePath(unittest.TestCase):
    def test_passing_candidate_selects_hybrid_install(self):
        evaluations = [_eval(True, name="best", fit=0.95), _eval(False, name="worse", fit=0.99, license_verdict="unknown")]
        task_spec = TaskSpec(raw_prompt="x", goal="x")

        path, reason, best = decide_path(evaluations, task_spec)

        self.assertEqual(path, Path.HYBRID_INSTALL)
        self.assertEqual(best.candidate.name, "best")

    def test_multiple_passing_picks_highest_fit(self):
        evaluations = [_eval(True, name="a", fit=0.7), _eval(True, name="b", fit=0.95)]
        path, reason, best = decide_path(evaluations, TaskSpec(raw_prompt="x", goal="x"))

        self.assertEqual(best.candidate.name, "b")

    def test_no_pass_but_credentials_needed_asks_user(self):
        evaluations = [_eval(False, license_verdict="unknown")]
        task_spec = TaskSpec(raw_prompt="x", goal="x", estimated_permissions=["requires paid API key"])

        path, reason, best = decide_path(evaluations, task_spec)

        self.assertEqual(path, Path.ASK_USER)
        self.assertIsNone(best)

    def test_no_pass_no_credentials_needed_generates_code(self):
        evaluations = [_eval(False, license_verdict="unknown")]
        task_spec = TaskSpec(raw_prompt="x", goal="x")

        path, reason, best = decide_path(evaluations, task_spec)

        self.assertEqual(path, Path.CODE_GENERATION)

    def test_no_candidates_at_all_generates_code(self):
        path, reason, best = decide_path([], TaskSpec(raw_prompt="x", goal="x"))

        self.assertEqual(path, Path.CODE_GENERATION)
        self.assertIn("no candidates found", reason)


if __name__ == "__main__":
    unittest.main()
