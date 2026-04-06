"""
Document manager for loading and querying legal case documents.
All public APIs are doc-ID and sentence-range based.
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from state.schemas import DocumentCoverage, DocumentInfo


class DocumentManager:
    """
    Manages the corpus of legal documents.
    Provides sentence-level access and regex search over doc IDs.
    """

    def __init__(self, corpus_path: str, tokenizer=None, tokenizer_model: Optional[str] = None):
        """
        Initialize the document manager.

        Args:
            corpus_path: Path to the directory containing documents
            tokenizer: Unused in sentence mode; accepted for compatibility with caller wiring.
            tokenizer_model: Unused in sentence mode.
        """
        self.corpus_path = Path(corpus_path)
        self._doc_metadata_by_id: Dict[str, Dict[str, Any]] = {}
        self._filename_by_doc_id: Dict[str, str] = {}
        self._doc_ids_in_order: List[str] = []
        self._content_cache: Dict[str, str] = {}
        self._sentence_index_cache: Dict[str, List[Dict[str, Any]]] = {}

        if not self.corpus_path.exists():
            self.corpus_path.mkdir(parents=True, exist_ok=True)

        self._load_metadata()

    def _load_metadata(self):
        """Load document metadata from metadata.json."""
        metadata_file = self.corpus_path / "metadata.json"
        if not metadata_file.exists():
            raise ValueError(f"No metadata.json found in corpus directory: {self.corpus_path}")

        with open(metadata_file, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        documents = metadata.get("documents", [])
        for doc in documents:
            doc_id = str(doc.get("doc_id", "")).strip()
            filename = doc.get("filename")
            if not doc_id or not filename:
                continue
            if doc_id not in self._doc_metadata_by_id:
                self._doc_ids_in_order.append(doc_id)
            self._doc_metadata_by_id[doc_id] = doc
            self._filename_by_doc_id[doc_id] = filename

    def list_documents(self) -> List[str]:
        """Return available document IDs in metadata/request order."""
        if not self._doc_ids_in_order:
            raise ValueError("No documents available in metadata.json")
        return list(self._doc_ids_in_order)

    def load_document(self, doc_id: str, cache: bool = True) -> str:
        """
        Load a document's full text by doc ID.

        Args:
            doc_id: Stable document ID
            cache: Whether to cache loaded content

        Returns:
            Document content as string
        """
        if doc_id in self._content_cache:
            return self._content_cache[doc_id]

        filename = self._filename_by_doc_id.get(doc_id)
        if not filename:
            raise FileNotFoundError(f"Unknown document ID: {doc_id}")

        doc_path = self.corpus_path / filename
        if not doc_path.exists():
            raise FileNotFoundError(f"Document file not found for doc_id={doc_id}: {doc_path}")

        try:
            with open(doc_path, "r", encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            with open(doc_path, "r", encoding="latin-1") as f:
                content = f.read()

        if cache:
            self._content_cache[doc_id] = content
        return content

    def _load_sentence_index(self, doc_id: str) -> List[Dict[str, Any]]:
        """Load sentence index sidecar for a document."""
        if doc_id in self._sentence_index_cache:
            return self._sentence_index_cache[doc_id]

        metadata = self._doc_metadata_by_id.get(doc_id)
        if not metadata:
            raise FileNotFoundError(f"Unknown document ID: {doc_id}")

        sentence_index_file = metadata.get("sentence_index_file")
        if not sentence_index_file:
            raise FileNotFoundError(f"Missing sentence_index_file in metadata for doc_id={doc_id}")

        path = self.corpus_path / sentence_index_file
        if not path.exists():
            raise FileNotFoundError(f"Sentence index missing for doc_id={doc_id}: {path}")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        sentences = data.get("sentences", [])

        # Normalize IDs to ints and keep deterministic order.
        normalized = []
        for record in sentences:
            normalized.append(
                {
                    "sentence_id": int(record["sentence_id"]),
                    "text": record["text"],
                    "start_char": int(record["start_char"]),
                    "end_char": int(record["end_char"]),
                }
            )
        normalized.sort(key=lambda r: r["sentence_id"])

        self._sentence_index_cache[doc_id] = normalized
        return normalized

    def get_document_type(self, doc_id: str) -> str:
        """Get document type by doc ID."""
        metadata = self._doc_metadata_by_id.get(doc_id, {})
        return metadata.get("doc_type", "Unknown")

    def get_sentence_count(self, doc_id: str) -> int:
        """Get sentence count for document by doc ID."""
        metadata = self._doc_metadata_by_id.get(doc_id, {})
        if "sentence_count" in metadata:
            return int(metadata["sentence_count"])
        return len(self._load_sentence_index(doc_id))

    def get_document_info(self, doc_id: str, ledger=None) -> DocumentInfo:
        """
        Get full document info with sentence coverage.

        Args:
            doc_id: Stable document ID
            ledger: Optional ledger for coverage information
        """
        if doc_id not in self._doc_metadata_by_id:
            raise FileNotFoundError(f"Unknown document ID: {doc_id}")

        visited = False
        coverage = DocumentCoverage()
        last_read = None

        if ledger:
            visited = doc_id in ledger.get_visited_documents()
            coverage = ledger.get_document_coverage(doc_id) or DocumentCoverage()
            last_read = ledger.get_last_read(doc_id)

        return DocumentInfo(
            doc_id=doc_id,
            type=self.get_document_type(doc_id),
            sentence_count=self.get_sentence_count(doc_id),
            visited=visited,
            coverage=coverage,
            last_read=last_read,
        )

    def read_sentence_range(self, doc_id: str, start_sentence: int, end_sentence: int) -> Tuple[str, int, int]:
        """
        Read an inclusive sentence range from a document.

        Returns:
            (text_block, actual_start_sentence, actual_end_sentence)
        """
        sentences = self._load_sentence_index(doc_id)
        if not sentences:
            return "", 1, 0

        sentence_count = len(sentences)
        actual_start = max(1, min(start_sentence, sentence_count))
        actual_end = max(actual_start, min(end_sentence, sentence_count))

        selected = sentences[actual_start - 1 : actual_end]
        lines = [f"[{s['sentence_id']}] {self._normalize_sentence_text(s['text'])}" for s in selected]
        return "\n".join(lines), actual_start, actual_end

    def search_document(
        self,
        doc_id: str,
        pattern: str,
        flags: Optional[List[str]] = None,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Search a document with regex and return matched sentence ranges.

        Each match snippet is rendered with a small context window:
        one sentence before and one sentence after the matched span
        (clamped to document boundaries).
        """
        content = self.load_document(doc_id)
        sentence_index = self._load_sentence_index(doc_id)

        regex_flags = 0
        for flag in flags or []:
            if flag == "IGNORECASE":
                regex_flags |= re.IGNORECASE
            elif flag == "MULTILINE":
                regex_flags |= re.MULTILINE
            elif flag == "DOTALL":
                regex_flags |= re.DOTALL

        try:
            regex = re.compile(pattern, regex_flags)
        except re.error as e:
            raise ValueError(f"Invalid regex pattern: {e}") from e

        matches = []
        max_sentence_id = sentence_index[-1]["sentence_id"] if sentence_index else 0
        for m in regex.finditer(content):
            start_sentence, end_sentence = self._char_span_to_sentence_span(
                sentence_index,
                m.start(),
                m.end(),
            )
            snippet_start = max(1, start_sentence - 1)
            snippet_end = min(max_sentence_id, end_sentence + 1)
            snippet = self._render_sentence_span(sentence_index, snippet_start, snippet_end)
            matches.append(
                {
                    "start_sentence": start_sentence,
                    "end_sentence": end_sentence,
                    "start_char": m.start(),
                    "end_char": m.end(),
                    "snippet": snippet,
                    "groups": m.groupdict(),
                    "pattern": pattern,
                    "flags": flags or [],
                }
            )
            if len(matches) >= top_k:
                break

        return matches

    def _char_span_to_sentence_span(
        self,
        sentence_index: List[Dict[str, Any]],
        start_char: int,
        end_char: int,
    ) -> Tuple[int, int]:
        """Map char offsets to inclusive sentence ID span."""
        if not sentence_index:
            return 1, 1

        start_sentence = sentence_index[0]["sentence_id"]
        end_sentence = sentence_index[-1]["sentence_id"]

        for s in sentence_index:
            if s["end_char"] > start_char:
                start_sentence = s["sentence_id"]
                break

        for s in sentence_index:
            if s["end_char"] >= end_char:
                end_sentence = s["sentence_id"]
                break

        if end_sentence < start_sentence:
            end_sentence = start_sentence
        return start_sentence, end_sentence

    def _render_sentence_span(
        self,
        sentence_index: List[Dict[str, Any]],
        start_sentence: int,
        end_sentence: int,
    ) -> str:
        """Render inclusive sentence span as one sentence per line."""
        lines = []
        for s in sentence_index[start_sentence - 1 : end_sentence]:
            lines.append(f"[{s['sentence_id']}] {self._normalize_sentence_text(s['text'])}")
        return "\n".join(lines)

    def _normalize_sentence_text(self, text: str) -> str:
        """Normalize whitespace for compact one-line display."""
        return re.sub(r"\s+", " ", text).strip()

    def clear_cache(self):
        """Clear in-memory caches."""
        self._content_cache.clear()
        self._sentence_index_cache.clear()
