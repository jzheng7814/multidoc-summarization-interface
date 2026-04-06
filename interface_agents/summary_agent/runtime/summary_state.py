"""Persistent summary draft state for the summary agent."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple


_PARAGRAPH_ID_RE = re.compile(r"^p(\d+)$")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SummaryStore:
    """Thread-safe JSON store for paragraph-based summary editing."""

    def __init__(self, storage_path: str = "summary_state.json"):
        self.storage_path = Path(storage_path)
        self.lock = Lock()
        self._paragraphs: List[Dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if not self.storage_path.exists():
            return

        try:
            with self.storage_path.open("r", encoding="utf-8") as f:
                payload = json.load(f) or {}
            paragraphs = payload.get("paragraphs") or []
            if isinstance(paragraphs, list):
                cleaned: List[Dict[str, Any]] = []
                for raw in paragraphs:
                    if not isinstance(raw, dict):
                        continue
                    paragraph_id = str(raw.get("paragraph_id") or "").strip()
                    text = str(raw.get("text") or "")
                    if not paragraph_id or not text.strip():
                        continue
                    cleaned.append(
                        {
                            "paragraph_id": paragraph_id,
                            "text": text,
                            "last_updated": str(raw.get("last_updated") or utc_now_iso()),
                        }
                    )
                self._paragraphs = cleaned
        except Exception as exc:
            print(f"Warning: failed to load summary store from {self.storage_path}: {exc}")
            self._paragraphs = []

    def _save(self) -> None:
        payload = {
            "paragraphs": self._paragraphs,
            "summary_text": self.get_summary_text(),
            "summary_stats": self.get_summary_stats(),
            "last_updated": utc_now_iso(),
        }
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        with self.storage_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def _next_paragraph_id(self) -> str:
        max_id = 0
        for paragraph in self._paragraphs:
            paragraph_id = str(paragraph.get("paragraph_id") or "")
            match = _PARAGRAPH_ID_RE.match(paragraph_id)
            if match:
                max_id = max(max_id, int(match.group(1)))
        return f"p{max_id + 1:03d}"

    def _resolve_index(
        self,
        paragraph_id: Optional[str] = None,
        index: Optional[int] = None,
    ) -> Tuple[Optional[int], Optional[str]]:
        if paragraph_id is not None:
            target = str(paragraph_id).strip()
            for idx, paragraph in enumerate(self._paragraphs):
                if paragraph.get("paragraph_id") == target:
                    return idx, None
            return None, f"Unknown paragraph_id: {target}"

        if index is not None:
            if index < 0 or index >= len(self._paragraphs):
                return None, f"index out of range: {index}"
            return index, None

        return None, "Must provide either paragraph_id or index"

    def reset(self, paragraphs: Optional[List[str]] = None) -> None:
        with self.lock:
            self._paragraphs = []
            if paragraphs:
                for text in paragraphs:
                    cleaned = str(text or "").strip()
                    if not cleaned:
                        continue
                    self._paragraphs.append(
                        {
                            "paragraph_id": self._next_paragraph_id(),
                            "text": cleaned,
                            "last_updated": utc_now_iso(),
                        }
                    )
            self._save()

    def get_paragraphs(self) -> List[Dict[str, Any]]:
        with self.lock:
            return [dict(p) for p in self._paragraphs]

    def get_summary_text(self) -> str:
        return "\n\n".join(str(p.get("text") or "").strip() for p in self._paragraphs if str(p.get("text") or "").strip())

    def get_summary_stats(self) -> Dict[str, Any]:
        text = self.get_summary_text()
        return {
            "paragraph_count": len(self._paragraphs),
            "character_count": len(text),
            "non_empty": bool(text.strip()),
        }

    def get_state(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "paragraphs": [dict(p) for p in self._paragraphs],
                "summary_text": self.get_summary_text(),
                "summary_stats": self.get_summary_stats(),
            }

    def append_paragraph(self, text: str, index: Optional[int] = None) -> Dict[str, Any]:
        cleaned = str(text or "").strip()
        if not cleaned:
            return {"error": "text must be non-empty"}

        with self.lock:
            paragraph = {
                "paragraph_id": self._next_paragraph_id(),
                "text": cleaned,
                "last_updated": utc_now_iso(),
            }
            if index is None or index >= len(self._paragraphs):
                self._paragraphs.append(paragraph)
                actual_index = len(self._paragraphs) - 1
            elif index < 0:
                return {"error": f"index out of range: {index}"}
            else:
                self._paragraphs.insert(index, paragraph)
                actual_index = index
            self._save()

            return {
                "appended_paragraph_id": paragraph["paragraph_id"],
                "index": actual_index,
                "summary_stats": self.get_summary_stats(),
            }

    def update_paragraph(
        self,
        text: str,
        paragraph_id: Optional[str] = None,
        index: Optional[int] = None,
    ) -> Dict[str, Any]:
        cleaned = str(text or "").strip()
        if not cleaned:
            return {"error": "text must be non-empty"}

        with self.lock:
            resolved_index, error = self._resolve_index(paragraph_id=paragraph_id, index=index)
            if error:
                return {"error": error}

            assert resolved_index is not None
            paragraph = self._paragraphs[resolved_index]
            paragraph["text"] = cleaned
            paragraph["last_updated"] = utc_now_iso()
            self._save()
            return {
                "updated_paragraph_id": paragraph.get("paragraph_id"),
                "index": resolved_index,
                "summary_stats": self.get_summary_stats(),
            }

    def delete_paragraph(
        self,
        paragraph_id: Optional[str] = None,
        index: Optional[int] = None,
    ) -> Dict[str, Any]:
        with self.lock:
            resolved_index, error = self._resolve_index(paragraph_id=paragraph_id, index=index)
            if error:
                return {"error": error}

            assert resolved_index is not None
            deleted = self._paragraphs.pop(resolved_index)
            self._save()
            return {
                "deleted_paragraph_id": deleted.get("paragraph_id"),
                "index": resolved_index,
                "summary_stats": self.get_summary_stats(),
            }
