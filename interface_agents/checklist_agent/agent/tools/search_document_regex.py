"""Search document regex tool - searches documents using regular expressions."""

from typing import Any, Dict, List

from pydantic import ValidationError

from .base import BaseTool
from agent.document_manager import DocumentManager
from state.schemas import (
    DocumentSearchResult,
    RegexMatch,
    SearchDocumentRegexInput,
    SearchDocumentRegexOutput,
    SearchEvent,
)
from state.store import Ledger


class SearchDocumentRegexTool(BaseTool):
    """
    Search one/many/all documents by doc_id with regex.
    Returns matched sentence ranges and full matched sentence lines.
    """

    def __init__(self, document_manager: DocumentManager, ledger: Ledger = None):
        super().__init__(
            name="search_document_regex",
            description="Search one or more documents (doc_id) using regex and return matched sentences",
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
                "doc_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specific document IDs to search",
                },
                "doc_id": {
                    "type": "string",
                    "description": "Single document ID or 'all' for all documents",
                },
                "pattern": {"type": "string"},
                "flags": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["IGNORECASE", "MULTILINE", "DOTALL"]},
                    "default": [],
                },
                "top_k": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
            },
            "required": ["pattern"],
        }

    def get_output_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "documents_searched": {"type": "array", "items": {"type": "string"}},
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "doc_id": {"type": "string"},
                            "match_count": {"type": "integer"},
                            "matches": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "start_sentence": {"type": "integer"},
                                        "end_sentence": {"type": "integer"},
                                        "start_char": {"type": "integer"},
                                        "end_char": {"type": "integer"},
                                        "snippet": {"type": "string"},
                                        "groups": {"type": "object"},
                                        "pattern": {"type": "string"},
                                        "flags": {"type": "array", "items": {"type": "string"}},
                                    },
                                },
                            },
                        },
                    },
                },
                "total_matches": {"type": "integer"},
            },
            "required": ["pattern", "documents_searched", "results", "total_matches"],
        }

    def call(self, args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if "doc_name" in args or "doc_names" in args or "context_tokens" in args:
                raise ValueError(
                    "search_document_regex no longer accepts name/token context args. "
                    "Use doc_id/doc_ids only."
                )

            input_data = self.validate_input(args, SearchDocumentRegexInput)

            all_doc_ids = self.document_manager.list_documents()
            if not all_doc_ids:
                raise ValueError("No documents available in corpus.")

            docs_to_search: List[str]
            if input_data.doc_ids:
                docs_to_search = input_data.doc_ids
            elif input_data.doc_id == "all" or not input_data.doc_id:
                docs_to_search = all_doc_ids
            else:
                docs_to_search = [input_data.doc_id]

            invalid_ids = [doc_id for doc_id in docs_to_search if doc_id not in all_doc_ids]
            if invalid_ids:
                raise ValueError(
                    f"Invalid doc_id(s): {', '.join(invalid_ids)}. "
                    f"Available IDs: {', '.join(all_doc_ids)}"
                )

            document_matches: Dict[str, List[tuple]] = {}
            document_results: List[DocumentSearchResult] = []
            total_matches = 0

            for doc_id in docs_to_search:
                matches = self.document_manager.search_document(
                    doc_id=doc_id,
                    pattern=input_data.pattern,
                    flags=input_data.flags,
                    top_k=input_data.top_k,
                )

                regex_matches = []
                for m in matches:
                    regex_matches.append(
                        RegexMatch(
                            start_sentence=m["start_sentence"],
                            end_sentence=m["end_sentence"],
                            start_char=m["start_char"],
                            end_char=m["end_char"],
                            snippet=m["snippet"],
                            groups=m["groups"],
                            pattern=m["pattern"],
                            flags=m["flags"],
                        )
                    )

                match_ranges = [(m.start_sentence, m.end_sentence) for m in regex_matches]
                document_matches[doc_id] = match_ranges

                if regex_matches:
                    document_results.append(
                        DocumentSearchResult(
                            doc_id=doc_id,
                            matches=regex_matches,
                            match_count=len(regex_matches),
                        )
                    )
                    total_matches += len(regex_matches)

            if self.ledger:
                self.ledger.record_search(
                    SearchEvent(
                        doc_id=input_data.doc_id if input_data.doc_id else None,
                        doc_ids=input_data.doc_ids if input_data.doc_ids else None,
                        pattern=input_data.pattern,
                        flags=input_data.flags,
                        matches_found=total_matches,
                        step=self._current_step,
                        document_matches=document_matches,
                    ),
                    self._run_id,
                )

            output = SearchDocumentRegexOutput(
                pattern=input_data.pattern,
                documents_searched=docs_to_search,
                results=document_results,
                total_matches=total_matches,
            )
            return self.format_output(output)

        except ValidationError as e:
            raise ValueError(f"Invalid input for search_document_regex: {e}") from e
        except ValueError:
            raise
        except Exception as e:
            raise Exception(f"Error searching document: {e}") from e
