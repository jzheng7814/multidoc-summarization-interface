import json
import tempfile
import unittest
from pathlib import Path

from app.services.cluster_checklist_spec import load_cluster_checklist_spec


class ClusterChecklistSpecTests(unittest.TestCase):
    def test_load_individual_spec_from_default_resource(self):
        spec = load_cluster_checklist_spec("app/resources/checklists/remote_checklist_spec.individual.json")
        self.assertIn("checklist_items", spec)
        self.assertIsInstance(spec["checklist_items"], list)
        self.assertGreater(len(spec["checklist_items"]), 0)
        first = spec["checklist_items"][0]
        self.assertIn("key", first)
        self.assertIn("description", first)
        self.assertIn("user_instruction", first)
        self.assertIn("constraints", first)
        self.assertIn("max_steps", first)
        self.assertIn("reasoning_effort", first)
        self.assertIsInstance(first["max_steps"], int)
        self.assertIn(first["reasoning_effort"], {"low", "medium", "high"})

    def test_rejects_invalid_individual_spec_shape(self):
        with tempfile.TemporaryDirectory(prefix="cluster_spec_test_") as temp_dir:
            path = Path(temp_dir) / "bad_spec.json"
            path.write_text(
                json.dumps(
                    {
                        "checklist_items": [
                            {
                                "key": "Filing_Date",
                                "description": "desc",
                                "user_instruction": "instruction",
                                "constraints": None,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeError):
                load_cluster_checklist_spec(str(path))

    def test_rejects_invalid_individual_reasoning_effort(self):
        with tempfile.TemporaryDirectory(prefix="cluster_spec_test_") as temp_dir:
            path = Path(temp_dir) / "bad_reasoning.json"
            path.write_text(
                json.dumps(
                    {
                        "checklist_items": [
                            {
                                "key": "Filing_Date",
                                "description": "desc",
                                "user_instruction": "instruction",
                                "constraints": ["must cite evidence"],
                                "max_steps": 200,
                                "reasoning_effort": "extreme",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeError):
                load_cluster_checklist_spec(str(path))


if __name__ == "__main__":
    unittest.main()
