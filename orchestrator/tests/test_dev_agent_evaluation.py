import unittest
from datetime import datetime, timedelta, timezone

from orchestrator.dev_agent.candidates import Candidate
from orchestrator.dev_agent.evaluation import (
    check_vulnerabilities,
    evaluate,
    judge_functional_fit,
    license_verdict,
    maintenance_ok,
)
from orchestrator.task_spec import TaskSpec
from tests.fakes import SchemaRoutedProvider


def _candidate(**overrides):
    defaults = dict(
        ecosystem="npm",
        name="some-pkg",
        description="does a thing",
        license="MIT",
        url="https://example.invalid",
        last_updated=datetime.now(timezone.utc).isoformat(),
        popularity=100,
    )
    defaults.update(overrides)
    return Candidate(**defaults)


class TestLicenseVerdict(unittest.TestCase):
    def test_allowed(self):
        self.assertEqual(license_verdict("MIT"), "allowed")

    def test_flagged_gpl_family(self):
        self.assertEqual(license_verdict("GPL-3.0"), "flagged")
        self.assertEqual(license_verdict("AGPL-3.0"), "flagged")

    def test_missing_is_unknown_not_assumed_safe(self):
        self.assertEqual(license_verdict(None), "unknown")

    def test_unrecognized_is_unknown(self):
        self.assertEqual(license_verdict("SomeWeirdLicense-1.0"), "unknown")


class TestMaintenanceOk(unittest.TestCase):
    def test_recent_update_passes(self):
        c = _candidate(last_updated=datetime.now(timezone.utc).isoformat(), popularity=None)
        self.assertTrue(maintenance_ok(c))

    def test_stale_update_and_low_popularity_fails(self):
        old = (datetime.now(timezone.utc) - timedelta(days=1000)).isoformat()
        c = _candidate(last_updated=old, popularity=1)
        self.assertFalse(maintenance_ok(c))

    def test_high_popularity_passes_even_if_stale(self):
        old = (datetime.now(timezone.utc) - timedelta(days=1000)).isoformat()
        c = _candidate(last_updated=old, popularity=10000)
        self.assertTrue(maintenance_ok(c))

    def test_no_data_at_all_fails(self):
        c = _candidate(last_updated=None, popularity=None)
        self.assertFalse(maintenance_ok(c))


class TestCheckVulnerabilities(unittest.TestCase):
    def test_queries_osv_with_correct_ecosystem_mapping(self):
        def fake_post(url, body):
            self.assertEqual(url, "https://api.osv.dev/v1/query")
            self.assertEqual(body, {"package": {"name": "requests", "ecosystem": "PyPI"}})
            return {"vulns": [{"id": "GHSA-xxxx"}]}

        result = check_vulnerabilities(_candidate(ecosystem="pypi", name="requests"), http_post=fake_post)

        self.assertEqual(len(result), 1)

    def test_github_ecosystem_skipped_no_query(self):
        result = check_vulnerabilities(_candidate(ecosystem="github"), http_post=lambda url, body: (_ for _ in ()).throw(AssertionError("should not be called")))
        self.assertEqual(result, [])


class TestJudgeFunctionalFit(unittest.TestCase):
    def test_returns_score_from_provider(self):
        provider = SchemaRoutedProvider({"score": {"score": 0.9, "reasoning": "good match"}})
        task_spec = TaskSpec(raw_prompt="x", goal="parse pdfs")

        score = judge_functional_fit(_candidate(), task_spec, provider)

        self.assertEqual(score, 0.9)


class TestEvaluate(unittest.TestCase):
    def test_full_pass(self):
        provider = SchemaRoutedProvider({"score": {"score": 0.9, "reasoning": "ok"}})
        candidate = _candidate(license="MIT", popularity=1000)

        result = evaluate(
            candidate,
            TaskSpec(raw_prompt="x", goal="x"),
            provider,
            http_post=lambda url, body: {"vulns": []},
        )

        self.assertTrue(result.passes)

    def test_fails_on_flagged_license_even_with_good_fit(self):
        provider = SchemaRoutedProvider({"score": {"score": 0.95, "reasoning": "ok"}})
        candidate = _candidate(license="GPL-3.0", popularity=1000)

        result = evaluate(
            candidate,
            TaskSpec(raw_prompt="x", goal="x"),
            provider,
            http_post=lambda url, body: {"vulns": []},
        )

        self.assertFalse(result.passes)

    def test_fails_on_vulnerabilities(self):
        provider = SchemaRoutedProvider({"score": {"score": 0.95, "reasoning": "ok"}})
        candidate = _candidate(license="MIT", popularity=1000)

        result = evaluate(
            candidate,
            TaskSpec(raw_prompt="x", goal="x"),
            provider,
            http_post=lambda url, body: {"vulns": [{"id": "GHSA-yyyy"}]},
        )

        self.assertFalse(result.passes)


if __name__ == "__main__":
    unittest.main()
