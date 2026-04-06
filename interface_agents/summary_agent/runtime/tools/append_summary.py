"""Tool for appending a paragraph to the summary draft."""

from __future__ import annotations

from typing import Any, Dict

from runtime.base_tool import BaseTool
from runtime.summary_state import SummaryStore


class AppendSummaryTool(BaseTool):
    """Append one paragraph at end or by explicit index insertion."""

    def __init__(self, store: SummaryStore):
        super().__init__(
            name="append_summary",
            description="Append a new summary paragraph (plain narrative text, no bullets)",
        )
        self.store = store

    def get_input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Paragraph text to append",
                },
                "index": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Optional insertion index (0-based)",
                },
            },
            "required": ["text"],
        }

    def get_output_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "appended_paragraph_id": {"type": "string"},
                "index": {"type": "integer"},
                "summary_stats": {"type": "object"},
                "error": {"type": "string"},
            },
            "required": ["success"],
        }

    def call(self, args: Dict[str, Any]) -> Dict[str, Any]:
        text = str((args or {}).get("text") or "")
        index = (args or {}).get("index")

        if index is not None:
            try:
                index = int(index)
            except (TypeError, ValueError):
                return {"success": False, "error": "index must be an integer"}

        result = self.store.append_paragraph(text=text, index=index)
        if result.get("error"):
            return {"success": False, "error": result["error"]}
        result["success"] = True
        return result
