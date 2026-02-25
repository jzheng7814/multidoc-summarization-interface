from __future__ import annotations

import asyncio
from datetime import datetime
import json
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import HTTPException

from app.eventing import bind_event_case_id, get_event_producer, reset_event_case_id
from app.data.checklist_store import (
    DocumentChecklistStore,
    SqlDocumentChecklistStore,
    StoredDocumentChecklist,
)
from app.schemas.checklists import (
    EvidenceCategory,
    EvidenceCategoryCollection,
    EvidenceCategoryValue,
    EvidenceCollection,
    EvidenceItem,
    EvidencePointer,
)
from app.schemas.documents import DocumentReference
from app.services.checklist_engines import get_checklist_extraction_engine
from app.services.documents import get_document

producer = get_event_producer(__name__)

_ASSET_DIR = Path(__file__).resolve().parents[1] / "resources" / "checklists"
_ITEM_DESCRIPTIONS_PATH = _ASSET_DIR / "item_specific_info_improved.json"
_CATEGORY_METADATA_PATH = _ASSET_DIR / "v2" / "category_metadata.json"

_CHECKLIST_VERSION = "evidence-items-v1"

if not _ITEM_DESCRIPTIONS_PATH.exists():
    raise RuntimeError(f"Checklist item descriptions not found at {_ITEM_DESCRIPTIONS_PATH}")
if not _CATEGORY_METADATA_PATH.exists():
    raise RuntimeError(f"Checklist category metadata not found at {_CATEGORY_METADATA_PATH}")

_CHECKLIST_ITEM_DESCRIPTIONS: Dict[str, str] = json.loads(_ITEM_DESCRIPTIONS_PATH.read_text(encoding="utf-8"))
_CATEGORY_METADATA: List[Dict[str, object]] = json.loads(_CATEGORY_METADATA_PATH.read_text(encoding="utf-8"))

_CATEGORY_LOOKUP: Dict[str, Dict[str, object]] = {}
_CATEGORY_BY_ITEM: Dict[str, str] = {}
for category in _CATEGORY_METADATA:
    category_id = category.get("id")
    members = category.get("members") or []
    if not isinstance(category_id, str):
        raise RuntimeError("Checklist category metadata entries must include string 'id' keys.")
    if category_id in _CATEGORY_LOOKUP:
        raise RuntimeError(f"Duplicate checklist category id detected: {category_id}")
    _CATEGORY_LOOKUP[category_id] = {
        "id": category_id,
        "label": category.get("label") or category_id,
        "color": category.get("color") or "#000000",
        "members": list(members),
    }
    for member in members:
        if member in _CATEGORY_BY_ITEM:
            raise RuntimeError(f"Checklist item '{member}' assigned to multiple categories.")
        _CATEGORY_BY_ITEM[member] = category_id

_CATEGORY_ORDER = [category["id"] for category in _CATEGORY_METADATA if isinstance(category.get("id"), str)]

_DOCUMENT_CHECKLIST_STORE: DocumentChecklistStore = SqlDocumentChecklistStore()


class ExtractionRunManager:
    """Monolithic coordinator for checklist extraction runs keyed by case_id."""

    def __init__(self, store: DocumentChecklistStore) -> None:
        self._store = store
        self._lock = asyncio.Lock()
        self._global_lock = asyncio.Lock()
        self._in_flight: Dict[str, asyncio.Task[EvidenceCollection]] = {}

    async def get_cached(self, case_id: str, documents: List[DocumentReference]) -> EvidenceCollection | None:
        stored = self._store.get(case_id)
        if stored is None:
            return None
        sorted_docs = sorted(documents, key=_document_sort_key)
        text_lookup = _build_text_lookup_from_references(case_id, sorted_docs)
        sanitized_items = _strip_sentence_ids_from_collection(stored.items, text_lookup)
        if sanitized_items != stored.items:
            self._store.set(
                case_id,
                items=sanitized_items,
                version=stored.version,
            )
        return sanitized_items

    async def ensure_record(self, case_id: str, documents: List[DocumentReference]) -> StoredDocumentChecklist:
        stored = self._store.get(case_id)
        if stored is not None:
            sorted_docs = sorted(documents, key=_document_sort_key)
            text_lookup = _build_text_lookup_from_references(case_id, sorted_docs)
            sanitized_items = _strip_sentence_ids_from_collection(stored.items, text_lookup)
            if sanitized_items != stored.items:
                self._store.set(
                    case_id,
                    items=sanitized_items,
                    version=stored.version,
                )
            return StoredDocumentChecklist(items=sanitized_items, version=stored.version)

        await self.ensure_extraction(case_id, documents)
        stored = self._store.get(case_id)
        if stored is None:
            raise RuntimeError(f"Checklist extraction for case {case_id} failed to persist.")
        return stored

    async def ensure_extraction(self, case_id: str, documents: List[DocumentReference]) -> EvidenceCollection:
        if not documents:
            return EvidenceCollection(items=[])

        cached = await self.get_cached(case_id, documents)
        if cached is not None:
            return _copy_collection(cached)

        case_key = str(case_id)
        async with self._lock:
            task = self._in_flight.get(case_key)
            if task is None or task.done():
                task = asyncio.create_task(self._run_extraction(case_id, documents))
                self._in_flight[case_key] = task

        try:
            result = await task
        finally:
            if task.done():
                async with self._lock:
                    current = self._in_flight.get(case_key)
                    if current is task:
                        self._in_flight.pop(case_key, None)

        return _copy_collection(result)

    async def _run_extraction(self, case_id: str, documents: List[DocumentReference]) -> EvidenceCollection:
        sorted_docs = sorted(documents, key=_document_sort_key)
        text_lookup = _build_text_lookup_from_references(case_id, sorted_docs)

        if self._global_lock.locked():
            producer.info("Checklist extraction queued behind active run", {"case_id": case_id})

        async with self._global_lock:
            producer.info("Checklist extraction acquired global run lock", {"case_id": case_id})
            stored = self._store.get(case_id)
            if stored is not None:
                sanitized_items = _strip_sentence_ids_from_collection(stored.items, text_lookup)
                if sanitized_items != stored.items:
                    self._store.set(
                        case_id,
                        items=sanitized_items,
                        version=stored.version,
                    )
                return _copy_collection(sanitized_items)

            result = await _run_extraction(case_id, sorted_docs, text_lookup)
            return _copy_collection(result)


_EXTRACTION_RUN_MANAGER = ExtractionRunManager(_DOCUMENT_CHECKLIST_STORE)


def get_checklist_definitions() -> Dict[str, str]:
    """Return a copy of the checklist item descriptions."""
    return dict(_CHECKLIST_ITEM_DESCRIPTIONS)


def get_category_metadata(include_members: bool = False) -> List[Dict[str, object]]:
    """Return checklist category metadata for UI consumption."""
    metadata: List[Dict[str, object]] = []
    for category_id in _CATEGORY_ORDER:
        category = _CATEGORY_LOOKUP[category_id]
        if include_members:
            metadata.append(
                {
                    "id": category["id"],
                    "label": category["label"],
                    "color": category["color"],
                    "members": list(category.get("members", [])),
                }
            )
        else:
            metadata.append(
                {
                    "id": category["id"],
                    "label": category["label"],
                    "color": category["color"],
                }
            )
    return metadata


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _document_sort_key(doc_ref: DocumentReference) -> tuple:
    if doc_ref.is_docket:
        return (0, doc_ref.id)
    date_value = _parse_date(doc_ref.date)
    if date_value is None:
        return (1, 1, 0, doc_ref.id)
    return (1, 0, -date_value.timestamp(), doc_ref.id)


def _resolve_document_payloads(case_id: str, documents: List[DocumentReference]) -> List[Dict[str, str]]:
    payloads: List[Dict[str, str]] = []
    for doc_ref in documents:
        if doc_ref.include_full_text:
            if not doc_ref.content:
                raise HTTPException(status_code=400, detail=f"Document '{doc_ref.id}' missing inline content.")
            text = doc_ref.content
            title = doc_ref.title or doc_ref.alias or doc_ref.id
            doc_type = None
        else:
            document = get_document(case_id, doc_ref.id)
            text = doc_ref.content or document.content
            title = doc_ref.title or doc_ref.alias or document.title or document.id
            doc_type = document.type

        payloads.append(
            {
                "id": int(doc_ref.id),
                "title": title,
                "type": doc_type or "",
                "text": text or "",
            }
        )
    return payloads


def _build_text_lookup_from_references(case_id: str, documents: List[DocumentReference]) -> Dict[int, str]:
    payloads = _resolve_document_payloads(case_id, documents)
    return {int(payload["id"]): payload.get("text", "") for payload in payloads}


def _copy_collection(collection: EvidenceCollection) -> EvidenceCollection:
    return collection.model_copy(deep=True)


async def get_document_checklists_if_cached(
    case_id: str, documents: List[DocumentReference]
) -> EvidenceCollection | None:
    return await _EXTRACTION_RUN_MANAGER.get_cached(case_id, documents)


async def ensure_document_checklist_record(
    case_id: str, documents: List[DocumentReference]
) -> StoredDocumentChecklist:
    """Ensure checklist extraction results exist for a case and return the stored payload."""
    stored = await _EXTRACTION_RUN_MANAGER.ensure_record(case_id, documents)
    return stored


def _strip_sentence_ids_from_collection(
    collection: EvidenceCollection, text_lookup: Optional[Dict[int, str]] = None
) -> EvidenceCollection:
    """Return a copy with evidence text populated when possible."""
    cleaned_items: List[EvidenceItem] = []
    for item in collection.items:
        ev = item.evidence
        doc_text = (text_lookup or {}).get(ev.document_id)
        start = ev.start_offset
        end = ev.end_offset
        text = ev.text
        if doc_text is not None and start is not None and end is not None and 0 <= start < end <= len(doc_text):
            text = doc_text[start:end]
        cleaned_items.append(
            EvidenceItem(
                bin_id=item.bin_id,
                value=item.value,
                evidence=EvidencePointer(
                    document_id=ev.document_id,
                    location=ev.location,
                    start_offset=start,
                    end_offset=end,
                    text=text,
                    verified=ev.verified,
                ),
            )
        )
    return EvidenceCollection(items=cleaned_items)


def build_category_collection(record: StoredDocumentChecklist) -> EvidenceCategoryCollection:
    """Map extracted evidence items into UI categories."""
    sanitized_items = _strip_sentence_ids_from_collection(record.items)
    categories: Dict[str, EvidenceCategory] = {
        meta_id: EvidenceCategory(
            id=meta_id,
            label=_CATEGORY_LOOKUP[meta_id]["label"],
            color=_CATEGORY_LOOKUP[meta_id]["color"],
            values=[],
        )
        for meta_id in _CATEGORY_ORDER
    }

    bin_counters: Dict[str, int] = {meta_id: 0 for meta_id in _CATEGORY_ORDER}

    for item in sanitized_items.items:
        category_id = _CATEGORY_BY_ITEM.get(item.bin_id, item.bin_id)
        category = categories.get(category_id)
        if not category:
            continue
        value_index = bin_counters[category_id]
        bin_counters[category_id] += 1
        ev = item.evidence
        value_id = _build_ai_value_id(item.bin_id, value_index)
        category.values.append(
            EvidenceCategoryValue(
                id=value_id,
                value=item.value,
                text=item.value,
                document_id=ev.document_id,
                start_offset=ev.start_offset,
                end_offset=ev.end_offset,
            )
        )

    ordered = [categories[category_id] for category_id in _CATEGORY_ORDER]
    return EvidenceCategoryCollection(categories=ordered)


def _build_ai_value_id(bin_id: str, value_index: int) -> str:
    return f"ai::{bin_id}::{value_index}"


async def extract_document_checklists(case_id: str, documents: List[DocumentReference]) -> EvidenceCollection:
    return await _EXTRACTION_RUN_MANAGER.ensure_extraction(case_id, documents)


async def _run_extraction(
    case_id: str, documents: List[DocumentReference], text_lookup: Dict[int, str]
) -> EvidenceCollection:
    token = bind_event_case_id(case_id)
    try:
        engine = get_checklist_extraction_engine()
        producer.info(
            "Checklist extraction engine selected",
            {"case_id": case_id, "engine": engine.name},
        )
        result = await engine.run(case_id, documents)

        sanitized_items = _strip_sentence_ids_from_collection(result, text_lookup)
        _DOCUMENT_CHECKLIST_STORE.set(case_id, items=sanitized_items, version=_CHECKLIST_VERSION)
        return _copy_collection(sanitized_items)

    except Exception as exc:
        producer.error("Checklist extraction failed", {"case_id": case_id, "error": str(exc)})
        raise
    finally:
        reset_event_case_id(token)
