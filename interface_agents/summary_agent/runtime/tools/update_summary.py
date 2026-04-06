"""Tool for revising an existing summary paragraph."""

from __future__ import annotations

from typing import Any, Dict, Optional

from runtime.base_tool import BaseTool
from runtime.summary_state import SummaryStore


class UpdateSummaryTool(BaseTool):
    """Replace text for an existing paragraph by id or 0-based index."""

    def __init__(self, store: SummaryStore):
        super().__init__(
            name="update_summary",
            description="Update an existing summary paragraph by paragraph_id or index",
        )
        self.store = store

    def get_input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "paragraph_id": {
                    "type": "string",
                    "description": "Target paragraph identifier (e.g., p001)",
                },
                "index": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Target paragraph index (0-based)",
                },
                "text": {
                    "type": "string",
                    "description": "Replacement paragraph text",
                },
            },
            "required": ["text"],
        }

    def get_output_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "updated_paragraph_id": {"type": "string"},
                "index": {"type": "integer"},
                "summary_stats": {"type": "object"},
                "error": {"type": "string"},
            },
            "required": ["success"],
        }

    def call(self, args: Dict[str, Any]) -> Dict[str, Any]:
        args = args or {}
        text = str(args.get("text") or "")
        paragraph_id = args.get("paragraph_id")
        index = self._parse_index(args.get("index"))
        if isinstance(index, str):
            return {"success": False, "error": index}

        result = self.store.update_paragraph(
            text=text,
            paragraph_id=str(paragraph_id).strip() if paragraph_id is not None else None,
            index=index,
        )
        if result.get("error"):
            return {"success": False, "error": result["error"]}
        result["success"] = True
        return result

    @staticmethod
    def _parse_index(raw: Any) -> Optional[int] | str:
        if raw is None:
            return None
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return "index must be an integer"
        if value < 0:
            return "index must be >= 0"
        return value
