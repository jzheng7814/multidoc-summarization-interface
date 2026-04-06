"""Tool for updating persisted derived-state memory in native runtime."""

from __future__ import annotations

from typing import Any, Dict

from agent.tools.base import BaseTool
from state.store import DerivedStateStore


class UpdateDerivedStateTool(BaseTool):
    """Update the native derived-state memory board."""

    def __init__(self, store: DerivedStateStore):
        super().__init__(
            name="update_derived_state",
            description=(
                "Apply one derived-state change at a time for buckets "
                "(confirmed_state, open_questions, external_refs). "
                "Use action=upsert or action=remove. "
                "confirmed_state upserts must include source_document_ids."
            ),
        )
        self.store = store

    def get_input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "bucket": {
                    "type": "string",
                    "enum": ["confirmed_state", "open_questions", "external_refs"],
                    "description": "Target derived-state bucket",
                },
                "action": {
                    "type": "string",
                    "enum": ["upsert", "remove"],
                    "description": "Single change action",
                },
                "text": {
                    "type": "string",
                    "description": "Entry text to insert/update/remove",
                },
                "source_document_ids": {
                    "type": "array",
                    "description": (
                        "Supporting document IDs. Pass [] for non-confirmed buckets. "
                        "For confirmed_state upsert, must be non-empty."
                    ),
                    "items": {"type": "string"},
                },
            },
            "required": ["bucket", "action", "text", "source_document_ids"],
        }

    def get_output_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "updated_buckets": {"type": "array", "items": {"type": "string"}},
                "validation_errors": {"type": "array", "items": {"type": "string"}},
                "success": {"type": "boolean"},
                "max_pinned_per_bucket": {"type": "integer"},
                "pinned_counts": {
                    "type": "object",
                    "properties": {
                        "confirmed_state": {"type": "integer"},
                        "open_questions": {"type": "integer"},
                        "external_refs": {"type": "integer"},
                    },
                    "required": ["confirmed_state", "open_questions", "external_refs"],
                },
                "derived_state": {
                    "type": "object",
                    "description": "Pinned derived-state snapshot after applying operations",
                },
            },
            "required": [
                "updated_buckets",
                "validation_errors",
                "success",
                "max_pinned_per_bucket",
                "pinned_counts",
                "derived_state",
            ],
        }

    def call(self, args: Dict[str, Any]) -> Dict[str, Any]:
        payload = args or {}
        if "operations" in payload:
            return {
                "updated_buckets": [],
                "validation_errors": [
                    "operations array is no longer supported; send one change object with bucket/action/text/source_document_ids"
                ],
                "success": False,
                "max_pinned_per_bucket": self.store.MAX_PINNED_PER_BUCKET,
                "pinned_counts": {
                    "confirmed_state": 0,
                    "open_questions": 0,
                    "external_refs": 0,
                },
                "derived_state": self.store.get_state(include_unpinned=False).dict(),
            }
        return self.store.apply_change(payload)
