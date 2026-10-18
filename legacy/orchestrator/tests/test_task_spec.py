import unittest

from orchestrator.task_spec import TaskSpec


class TestTaskSpec(unittest.TestCase):
    def test_round_trip_dict(self):
        spec = TaskSpec(
            raw_prompt="hello",
            goal="say hello",
            constraints=["offline only"],
            estimated_permissions=["filesystem:read"],
            capability_tags=["greeting"],
        )

        restored = TaskSpec.from_dict(spec.to_dict())

        self.assertEqual(spec, restored)

    def test_defaults_are_not_shared_between_instances(self):
        a = TaskSpec(raw_prompt="a", goal="a")
        b = TaskSpec(raw_prompt="b", goal="b")

        a.constraints.append("x")

        self.assertEqual(b.constraints, [])


if __name__ == "__main__":
    unittest.main()
