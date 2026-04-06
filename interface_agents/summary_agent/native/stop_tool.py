"""Two-stage stop tool for summary-agent native runtime."""

from __future__ import annotations

from typing import Any, Dict

from runtime.base_tool import BaseTool
from runtime.summary_state import SummaryStore


class StopTool(BaseTool):
    """Stage-1 review then stage-2 finalize termination."""

    def __init__(self, store: SummaryStore):
        super().__init__(
            name="stop",
            description=(
                "Request staged termination. First call triggers automatic summary-state review; "
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
                    "description": "Brief reason for requesting stop",
                }
            },
            "required": [],
        }

    def get_output_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "reason": {"type": "string"},
                "summary_stats": {"type": "object"},
                "stage": {"type": "string", "enum": ["review", "finalize"]},
                "terminated": {"type": "boolean"},
                "message": {"type": "string"},
            },
            "required": ["reason", "summary_stats", "stage", "terminated", "message"],
        }

    def call(self, args: Dict[str, Any]) -> Dict[str, Any]:
        reason = str((args or {}).get("reason") or "").strip()
        return {
            "reason": reason,
            "summary_stats": self.store.get_summary_stats(),
            "stage": "review",
            "terminated": False,
            "message": "",
        }
