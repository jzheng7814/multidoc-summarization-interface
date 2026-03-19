import unittest
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from pathlib import Path

from app.services.summary_focus_context import (
    build_summary_focus_context,
    load_default_summary_focus_context,
    render_summary_focus_context_template,
)


class SummaryFocusContextTests(unittest.TestCase):
    def test_render_template_replaces_placeholders(self):
        rendered = render_summary_focus_context_template(
            "Case #CASE_TITLE",
            {"CASE_TITLE": "Example Case"},
        )
        self.assertEqual(rendered, "Case Example Case")

    def test_build_focus_context_raises_on_missing_runtime_value(self):
        with self.assertRaises(RuntimeError):
            build_summary_focus_context(
                case_title=None,
                request_focus_context="Case title: #CASE_TITLE",
            )

    def test_build_focus_context_accepts_request_override_without_placeholders(self):
        rendered = build_summary_focus_context(
            case_title=None,
            request_focus_context="Only summarize dispositive orders.",
        )
        self.assertEqual(rendered, "Only summarize dispositive orders.")

    def test_load_default_summary_focus_context_uses_configured_path(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "focus_context.template.txt"
            path.write_text("Case: #CASE_TITLE", encoding="utf-8")
            settings = SimpleNamespace(cluster_summary_focus_context_template_path=str(path))
            template = load_default_summary_focus_context(settings)
            self.assertEqual(template, "Case: #CASE_TITLE")


if __name__ == "__main__":
    unittest.main()
