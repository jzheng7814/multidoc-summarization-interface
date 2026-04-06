"""Read document tool - reads a specific sentence range from a document."""

from typing import Any, Dict

from pydantic import ValidationError

from .base import BaseTool
from agent.document_manager import DocumentManager
from state.schemas import ReadDocumentInput, ReadDocumentOutput, ReadEvent
from state.store import Ledger


class ReadDocumentTool(BaseTool):
    """
    Tool for reading specific sentence ranges from documents.
    Records read events in the ledger for coverage tracking.
    """

    def __init__(self, document_manager: DocumentManager, ledger: Ledger = None):
        super().__init__(
            name="read_document",
            description="Read an inclusive sentence range from a document by doc_id",
        )
        self.document_manager = document_manager
        self.ledger = ledger
        self._current_step = 0
        self._run_id = "default"

    def set_context(self, run_id: str, step: int):
        self._run_id = run_id
        self._current_step = step

    def get_input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "doc_id": {"type": "string"},
                "start_sentence": {"type": "integer", "minimum": 1},
                "end_sentence": {"type": "integer", "minimum": 1},
                "purpose": {
                    "type": "string",
                    "enum": ["scan", "confirm"],
                    "default": "scan",
                },
            },
            "required": ["doc_id", "start_sentence", "end_sentence"],
        }

    def get_output_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "doc_id": {"type": "string"},
                "start_sentence": {"type": "integer"},
                "end_sentence": {"type": "integer"},
                "text": {"type": "string"},
            },
            "required": ["doc_id", "start_sentence", "end_sentence", "text"],
        }

    def call(self, args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            # Backward-incompatible hard cut: reject legacy token params.
            if "doc_name" in args or "start_token" in args or "end_token" in args:
                raise ValueError(
                    "read_document no longer accepts token-based args. "
                    "Use doc_id/start_sentence/end_sentence."
                )

            input_data = self.validate_input(args, ReadDocumentInput)

            available_doc_ids = self.document_manager.list_documents()
            if input_data.doc_id not in available_doc_ids:
                raise ValueError(
                    f"Document ID not found: '{input_data.doc_id}'. "
                    f"Available IDs: {', '.join(available_doc_ids)}"
                )

            text, actual_start, actual_end = self.document_manager.read_sentence_range(
                input_data.doc_id,
                input_data.start_sentence,
                input_data.end_sentence,
            )

            if self.ledger:
                read_event = ReadEvent(
                    doc_id=input_data.doc_id,
                    start_sentence=actual_start,
                    end_sentence=actual_end,
                    sentences_read=(actual_end - actual_start + 1),
                    step=self._current_step,
                )
                self.ledger.record_read(read_event, self._run_id)

            output = ReadDocumentOutput(
                doc_id=input_data.doc_id,
                start_sentence=actual_start,
                end_sentence=actual_end,
                text=text,
            )
            return self.format_output(output)

        except ValidationError as e:
            raise ValueError(f"Invalid input for read_document: {e}") from e
        except ValueError:
            raise
        except Exception as e:
            raise Exception(f"Error reading document: {e}") from e
