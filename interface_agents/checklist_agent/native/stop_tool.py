"""Native stop tool for two-stage termination."""

from __future__ import annotations

from typing import Any, Dict

from agent.tools.base import BaseTool
from state.store import ChecklistStore


class StopTool(BaseTool):
    """Stop tool that returns checklist review metadata for staged termination."""

    def __init__(self, store: ChecklistStore):
        super().__init__(
            name="stop",
            description=(
                "Request staged termination. First call triggers review flow; "
                "second call finalizes termination."
            ),
        )
        self.store = store

    def get_input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Brief reason for requesting termination",
                }
            },
            "required": [],
        }

    def get_output_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "reason": {"type": "string"},
                "completion_stats": {
                    "type": "object",
                    "properties": {
                        "filled": {"type": "integer"},
                        "empty": {"type": "integer"},
                        "total": {"type": "integer"},
                    },
                    "required": ["filled", "empty", "total"],
                },
                "empty_keys": {"type": "array", "items": {"type": "string"}},
                "stage": {"type": "string", "enum": ["review", "finalize"]},
                "terminated": {"type": "boolean"},
                "message": {"type": "string"},
            },
            "required": [
                "reason",
                "completion_stats",
                "empty_keys",
                "stage",
                "terminated",
                "message",
            ],
        }

    def call(self, args: Dict[str, Any]) -> Dict[str, Any]:
        # Stage/termination fields are set by the native driver.
        reason = str((args or {}).get("reason") or "").strip()
        stats = self.store.get_completion_stats()
        empty_keys = self.store.get_empty_keys()
        return {
            "reason": reason,
            "completion_stats": stats,
            "empty_keys": empty_keys,
            "stage": "review",
            "terminated": False,
            "message": "",
        }

