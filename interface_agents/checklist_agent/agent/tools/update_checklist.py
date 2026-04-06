"""
Update checklist tool - applies patches to update checklist items.
"""

from typing import Dict, Any, List
from pydantic import ValidationError
from .base import BaseTool
from state.store import ChecklistStore, Ledger
from state.schemas import UpdateChecklistInput, UpdateChecklistOutput, ChecklistPatch, UpdateEvent
from agent.document_manager import DocumentManager


class UpdateChecklistTool(BaseTool):
    """
    Tool for updating checklist items with extracted information.
    Validates that all extracted items have supporting evidence.
    """
    
    def __init__(self, store: ChecklistStore, ledger: Ledger = None, document_manager: DocumentManager = None):
        """
        Initialize the update_checklist tool.
        
        Args:
            store: ChecklistStore instance to update
            ledger: Optional Ledger instance for recording updates
        """
        super().__init__(
            name="update_checklist",
            description="Update checklist items with extracted information and evidence"
        )
        self.store = store
        self.ledger = ledger
        self.document_manager = document_manager
        self._current_step = 0
        self._run_id = "default"
    
    def set_context(self, run_id: str, step: int):
        """
        Set the current run context for ledger recording.
        
        Args:
            run_id: Current run ID
            step: Current step number
        """
        self._run_id = run_id
        self._current_step = step
    
    def get_input_schema(self) -> Dict[str, Any]:
        """
        Get the input schema for update_checklist.
        
        Returns:
            Schema for UpdateChecklistInput
        """
        return {
            "type": "object",
            "properties": {
                "patch": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string"},
                            "extracted": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "evidence": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "source_document_id": {"type": "string"},
                                                    "start_sentence": {"type": "integer"},
                                                    "end_sentence": {"type": "integer"}
                                                },
                                                "required": ["source_document_id", "start_sentence", "end_sentence"]
                                            }
                                        },
                                        "value": {"type": "string"}
                                    },
                                    "required": ["evidence", "value"]
                                }
                            },
                            "add_extracted": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "evidence": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "source_document_id": {"type": "string"},
                                                    "start_sentence": {"type": "integer"},
                                                    "end_sentence": {"type": "integer"}
                                                },
                                                "required": ["source_document_id", "start_sentence", "end_sentence"]
                                            }
                                        },
                                        "value": {"type": "string"}
                                    },
                                    "required": ["evidence", "value"]
                                }
                            },
                            "add_candidates": {
                                "type": "array",
                                "items": {"type": "object"}
                            }
                        },
                        "required": ["key"]
                    }
                }
            },
            "required": ["patch"]
        }
    
    def get_output_schema(self) -> Dict[str, Any]:
        """
        Get the output schema.
        
        Returns:
            Schema for UpdateChecklistOutput
        """
        return {
            "type": "object",
            "properties": {
                "updated_keys": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "validation_errors": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "success": {"type": "boolean"}
            },
            "required": ["updated_keys", "validation_errors", "success"]
        }
    
    def call(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the tool to update the checklist.
        
        Args:
            args: Dictionary containing 'patch' list
            
        Returns:
            Dictionary with updated keys, validation errors, and success status
        """
        try:
            # Validate input
            input_data = self.validate_input(args, UpdateChecklistInput)
            
            # Convert to ChecklistPatch objects if needed
            patches = []
            for patch_item in input_data.patch:
                try:
                    # Check if already a ChecklistPatch object or a dict
                    if isinstance(patch_item, ChecklistPatch):
                        patches.append(patch_item)
                    else:
                        # Convert dict to ChecklistPatch
                        patch = ChecklistPatch(**patch_item)
                        patches.append(patch)
                except ValidationError as e:
                    # Return validation error
                    return self.format_output(UpdateChecklistOutput(
                        updated_keys=[],
                        validation_errors=[f"Invalid patch: {e}"],
                        success=False
                    ))

            # Validate evidence doc IDs and sentence ranges.
            evidence_validation_errors = self._validate_evidence_ranges(patches)
            if evidence_validation_errors:
                return self.format_output(UpdateChecklistOutput(
                    updated_keys=[],
                    validation_errors=evidence_validation_errors,
                    success=False
                ))
            
            # Apply patches to the store
            updated_keys, validation_errors = self.store.update_items(patches)
            
            # Record in ledger if available
            if self.ledger and updated_keys:
                update_event = UpdateEvent(
                    keys_updated=updated_keys,
                    patch=patches,
                    step=self._current_step,
                    success=len(validation_errors) == 0
                )
                self.ledger.record_update(update_event, self._run_id)
            
            # Create output
            output = UpdateChecklistOutput(
                updated_keys=updated_keys,
                validation_errors=validation_errors,
                success=len(validation_errors) == 0
            )
            
            return self.format_output(output)
            
        except ValidationError as e:
            # Input validation failed
            return self.format_output(UpdateChecklistOutput(
                updated_keys=[],
                validation_errors=[str(e)],
                success=False
            ))
        except Exception as e:
            # Unexpected error
            return self.format_output(UpdateChecklistOutput(
                updated_keys=[],
                validation_errors=[f"Unexpected error: {str(e)}"],
                success=False
            ))

    def _validate_evidence_ranges(self, patches: List[ChecklistPatch]) -> List[str]:
        """Validate that all evidence doc IDs exist and sentence spans are in bounds."""
        errors: List[str] = []
        if not self.document_manager:
            return errors

        available_doc_ids = set(self.document_manager.list_documents())
        sentence_counts = {doc_id: self.document_manager.get_sentence_count(doc_id) for doc_id in available_doc_ids}

        def validate_evidence_item(key: str, value: str, ev) -> None:
            doc_id = ev.source_document_id
            if doc_id not in available_doc_ids:
                errors.append(
                    f"{key} value '{value}': unknown source_document_id '{doc_id}'"
                )
                return
            if ev.start_sentence < 1 or ev.end_sentence < ev.start_sentence:
                errors.append(
                    f"{key} value '{value}': invalid sentence range {ev.start_sentence}-{ev.end_sentence}"
                )
                return
            max_sentence = sentence_counts[doc_id]
            if ev.end_sentence > max_sentence:
                errors.append(
                    f"{key} value '{value}': sentence range {ev.start_sentence}-{ev.end_sentence} "
                    f"out of bounds for doc '{doc_id}' (max {max_sentence})"
                )

        for patch in patches:
            for ext in patch.extracted or []:
                for ev in ext.evidence:
                    validate_evidence_item(patch.key, ext.value, ev)
            for ext in patch.add_extracted or []:
                for ev in ext.evidence:
                    validate_evidence_item(patch.key, ext.value, ev)

        return errors
