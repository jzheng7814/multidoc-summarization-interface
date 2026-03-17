import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import cluster_focus_context


class ClusterFocusContextTests(unittest.TestCase):
    def test_load_cluster_focus_context_returns_non_empty_string(self):
        value = cluster_focus_context.load_cluster_focus_context()
        self.assertIsInstance(value, str)
        self.assertTrue(value.strip())

    def test_load_cluster_focus_context_rejects_missing_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "focus_context.yaml"
            path.write_text("wrong_key: value\n", encoding="utf-8")
            with patch.object(cluster_focus_context, "_focus_context_path", return_value=path):
                with self.assertRaises(RuntimeError):
                    cluster_focus_context.load_cluster_focus_context()

    def test_load_cluster_focus_context_rejects_empty_value(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "focus_context.yaml"
            path.write_text("focus_context: \"   \"\n", encoding="utf-8")
            with patch.object(cluster_focus_context, "_focus_context_path", return_value=path):
                with self.assertRaises(RuntimeError):
                    cluster_focus_context.load_cluster_focus_context()


if __name__ == "__main__":
    unittest.main()
