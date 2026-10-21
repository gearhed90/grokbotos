import unittest

from orchestrator.registry.db import AppRecord, AppRegistry


def _make_app(app_id="app.a", tags=None, success_rate=0.0, usage_count=0):
    return AppRecord(
        app_id=app_id,
        name=app_id,
        description="test app",
        capability_tags=tags or ["alpha", "beta"],
        input_schema={"type": "object"},
        output_schema={"type": "string"},
        exec_manifest={"entrypoint": "true", "runtime": "shell", "sandbox_profile_id": "none", "dependencies": []},
        creation_source="generated",
        version="0.1.0",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        success_rate=success_rate,
        usage_count=usage_count,
    )


class TestAppRegistry(unittest.TestCase):
    def setUp(self):
        self.registry = AppRegistry(":memory:")

    def tearDown(self):
        self.registry.close()

    def test_register_and_find_by_tags(self):
        self.registry.register(_make_app("app.a", tags=["alpha", "beta"]))
        self.registry.register(_make_app("app.b", tags=["gamma"]))

        matches = self.registry.find_by_tags(["alpha"])

        self.assertEqual([m.app_id for m in matches], ["app.a"])

    def test_no_match_returns_empty(self):
        self.registry.register(_make_app("app.a", tags=["alpha"]))

        self.assertEqual(self.registry.find_by_tags(["zzz"]), [])

    def test_tie_broken_by_success_rate(self):
        # Both share exactly one tag with the query -> tie on overlap count,
        # broken by success_rate per ROADMAP.md 2.3.
        self.registry.register(_make_app("app.low", tags=["shared"], success_rate=0.2))
        self.registry.register(_make_app("app.high", tags=["shared"], success_rate=0.9))

        matches = self.registry.find_by_tags(["shared"])

        self.assertEqual(matches[0].app_id, "app.high")

    def test_record_usage_updates_running_success_rate(self):
        self.registry.register(_make_app("app.a", success_rate=1.0, usage_count=1))

        self.registry.record_usage("app.a", used_at="2026-01-02T00:00:00Z", success=False)

        [updated] = self.registry.find_by_tags(["alpha"])
        self.assertEqual(updated.usage_count, 2)
        self.assertAlmostEqual(updated.success_rate, 0.5)


if __name__ == "__main__":
    unittest.main()
