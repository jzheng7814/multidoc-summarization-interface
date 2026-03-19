import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.services.cluster_focus_context import (
    load_cluster_focus_context,
    load_cluster_focus_context_template,
    render_cluster_focus_context_template,
)


class ClusterFocusContextTests(unittest.TestCase):
    def test_load_cluster_focus_context_returns_non_empty_string(self):
        value = load_cluster_focus_context("Example Case")
        self.assertIsInstance(value, str)
        self.assertTrue(value.strip())

    def test_render_template_replaces_case_title(self):
        rendered = render_cluster_focus_context_template(
            "Target: #CASE_TITLE",
            {"CASE_TITLE": "Case Name"},
        )
        self.assertEqual(rendered, "Target: Case Name")

    def test_load_cluster_focus_context_rejects_missing_case_title_for_placeholder(self):
        with self.assertRaises(RuntimeError):
            load_cluster_focus_context(None)

    def test_load_cluster_focus_context_template_uses_configured_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "focus_context.template.txt"
            path.write_text("Target: #CASE_TITLE", encoding="utf-8")
            settings = SimpleNamespace(cluster_focus_context_template_path=str(path))
            template = load_cluster_focus_context_template(settings)
            self.assertEqual(template, "Target: #CASE_TITLE")


if __name__ == "__main__":
    unittest.main()
