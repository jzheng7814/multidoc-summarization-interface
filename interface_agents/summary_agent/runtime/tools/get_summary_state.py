"""Tool for retrieving current summary draft state."""

from __future__ import annotations

from typing import Any, Dict

from runtime.base_tool import BaseTool
from runtime.summary_state import SummaryStore


class GetSummaryStateTool(BaseTool):
    """Return current paragraph draft and merged summary string."""

    def __init__(self, store: SummaryStore):
        super().__init__(
            name="get_summary_state",
            description="Retrieve the current summary draft (paragraphs + merged summary text)",
        )
        self.store = store

    def get_input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "include_paragraphs": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether to include paragraph-level records",
                }
            },
            "required": [],
        }

    def get_output_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "paragraphs": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "paragraph_id": {"type": "string"},
                            "text": {"type": "string"},
                            "last_updated": {"type": "string"},
                        },
                        "required": ["paragraph_id", "text", "last_updated"],
                    },
                },
                "summary_text": {"type": "string"},
                "summary_stats": {
                    "type": "object",
                    "properties": {
                        "paragraph_count": {"type": "integer"},
                        "character_count": {"type": "integer"},
                        "non_empty": {"type": "boolean"},
                    },
                    "required": ["paragraph_count", "character_count", "non_empty"],
                },
            },
            "required": ["summary_text", "summary_stats"],
        }

    def call(self, args: Dict[str, Any]) -> Dict[str, Any]:
        include_paragraphs = bool((args or {}).get("include_paragraphs", True))
        state = self.store.get_state()
        if not include_paragraphs:
            state.pop("paragraphs", None)
        return state
