from __future__ import annotations

import asyncio
import colorsys
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fastapi import HTTPException

from app.core.config import get_settings
from app.eventing import bind_event_case_id, get_event_producer, reset_event_case_id
from app.data.checklist_store import (
    DocumentChecklistStore,
    SqlDocumentChecklistStore,
    StoredDocumentChecklist,
)
from app.schemas.checklists import (
    ChecklistStatusResponse,
    EvidenceCategory,
    EvidenceCategoryCollection,
    EvidenceCategoryValue,
    EvidenceCollection,
    EvidenceItem,
    EvidencePointer,
)
from app.schemas.documents import DocumentReference
from app.services.cluster_checklist_spec import load_cluster_checklist_spec
from app.services.checklist_engines import get_checklist_extraction_engine
from app.services.documents import get_document

producer = get_event_producer(__name__)

_ASSET_DIR = Path(__file__).resolve().parents[1] / "resources" / "checklists"
_ITEM_DESCRIPTIONS_PATH = _ASSET_DIR / "item_specific_info_improved.json"

_CHECKLIST_VERSION = "evidence-items-v1"

if not _ITEM_DESCRIPTIONS_PATH.exists():
    raise RuntimeError(f"Checklist item descriptions not found at {_ITEM_DESCRIPTIONS_PATH}")

_CHECKLIST_ITEM_DESCRIPTIONS: Dict[str, str] = json.loads(_ITEM_DESCRIPTIONS_PATH.read_text(encoding="utf-8"))
_SETTINGS = get_settings()
_DOCUMENT_CHECKLIST_STORE: DocumentChecklistStore = SqlDocumentChecklistStore()
_UNSET = object()


def _rgb_to_hex(red: float, green: float, blue: float) -> str:
    return f"#{round(red * 255):02X}{round(green * 255):02X}{round(blue * 255):02X}"


def _build_distinct_color(index: int) -> str:
    # Golden-angle hue spacing keeps adjacent categories visually separated.
    hue = ((index * 137.508) % 360) / 360.0
    red, green, blue = colorsys.hls_to_rgb(hue, 0.50, 0.62)
    return _rgb_to_hex(red, green, blue)


def _build_item_category_metadata() -> List[Dict[str, object]]:
    try:
        spec = load_cluster_checklist_spec(
            _SETTINGS.cluster_checklist_spec_path,
            strategy=_SETTINGS.cluster_checklist_strategy,
        )
    except Exception as exc:  # pylint: disable=broad-except
        raise RuntimeError(
            "Unable to load checklist spec for checklist category ordering. "
            f"path={_SETTINGS.cluster_checklist_spec_path!r}, "
            f"strategy={_SETTINGS.cluster_checklist_strategy!r}, error={exc}"
        ) from exc

    raw_items = spec.get("checklist_items")
    if not isinstance(raw_items, list) or not raw_items:
        raise RuntimeError("Checklist spec did not contain a non-empty checklist_items array.")

    metadata: List[Dict[str, object]] = []
    for idx, item in enumerate(raw_items):
        key = item.get("key") if isinstance(item, dict) else None
        if not isinstance(key, str) or not key.strip():
            raise RuntimeError(f"Checklist item at index {idx} is missing a valid key.")
        cleaned_key = key.strip()
        metadata.append(
            {
                "id": cleaned_key,
                "label": cleaned_key,
                "color": _build_distinct_color(idx),
                "members": [cleaned_key],
            }
        )
    return metadata


_CATEGORY_METADATA: List[Dict[str, object]] = _build_item_category_metadata()

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


@dataclass(frozen=True)
class ChecklistRunState:
    checklist_status: str
    status_message: Optional[str] = None
    phase: Optional[str] = None
    slurm_state: Optional[str] = None
    current_step: Optional[int] = None
    max_steps: Optional[int] = None
    error: Optional[str] = None


class ExtractionRunManager:
    """Monolithic coordinator for checklist extraction runs keyed by case_id."""

    def __init__(self, store: DocumentChecklistStore) -> None:
        self._store = store
        self._lock = asyncio.Lock()
        self._global_lock = asyncio.Lock()
        self._in_flight: Dict[str, asyncio.Task[EvidenceCollection]] = {}
        self._status_by_case: Dict[str, ChecklistRunState] = {}

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

    async def get_status(self, case_id: str, documents: List[DocumentReference]) -> ChecklistStatusResponse:
        case_key = str(case_id)
        if not documents:
            self._update_status(
                case_key,
                checklist_status="empty",
                phase="empty",
                status_message="No documents available for checklist extraction.",
                error=None,
            )
            return self._status_response(self._status_by_case[case_key])

        cached = await self.get_cached(case_id, documents)
        if cached is not None:
            self._update_status(
                case_key,
                checklist_status="ready",
                phase="ready",
                status_message="Checklist is ready.",
                slurm_state=None,
                error=None,
            )
            return self._status_response(self._status_by_case[case_key], document_checklists=cached)

        state = self._status_by_case.get(case_key)
        if state is not None:
            return self._status_response(state)

        return ChecklistStatusResponse(
            checklist_status="pending",
            status_message="Checklist extraction has not been started.",
            phase="idle",
        )

    async def start_extraction(self, case_id: str, documents: List[DocumentReference]) -> ChecklistStatusResponse:
        case_key = str(case_id)
        if not documents:
            self._update_status(
                case_key,
                checklist_status="empty",
                phase="empty",
                status_message="No documents available for checklist extraction.",
                error=None,
            )
            return self._status_response(self._status_by_case[case_key])

        cached = await self.get_cached(case_id, documents)
        if cached is not None:
            self._update_status(
                case_key,
                checklist_status="ready",
                phase="ready",
                status_message="Checklist is ready.",
                slurm_state=None,
                error=None,
            )
            return self._status_response(self._status_by_case[case_key], document_checklists=cached)

        async with self._lock:
            task = self._in_flight.get(case_key)
            if task is not None and task.done():
                self._in_flight.pop(case_key, None)
                task = None

            if task is None and not _SETTINGS.checklist_start_enabled:
                self._update_status(
                    case_key,
                    checklist_status="failed",
                    phase="disabled",
                    status_message="Checklist extraction starts are disabled by configuration.",
                    error="checklist_start_disabled",
                )
                return self._status_response(self._status_by_case[case_key])

            if task is None:
                if self._global_lock.locked():
                    self._update_status(
                        case_key,
                        checklist_status="queued",
                        phase="queued",
                        status_message="Queued behind another checklist extraction run.",
                        error=None,
                    )
                else:
                    self._update_status(
                        case_key,
                        checklist_status="pending",
                        phase="starting",
                        status_message="Starting checklist extraction.",
                        error=None,
                    )

                task = asyncio.create_task(self._run_extraction(case_id, documents))
                task.add_done_callback(
                    lambda completed_task, target_case_key=case_key: asyncio.create_task(
                        self._finalize_task(target_case_key, completed_task)
                    )
                )
                self._in_flight[case_key] = task

        return self._status_response(self._status_by_case[case_key])

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

        await self.start_extraction(case_id, documents)
        case_key = str(case_id)
        async with self._lock:
            task = self._in_flight.get(case_key)

        if task is None:
            cached_after_start = await self.get_cached(case_id, documents)
            if cached_after_start is not None:
                return _copy_collection(cached_after_start)
            raise RuntimeError(f"Checklist extraction task was not created for case {case_id}.")

        result = await task
        return _copy_collection(result)

    async def _finalize_task(self, case_key: str, task: asyncio.Task[EvidenceCollection]) -> None:
        if task.cancelled():
            self._update_status(
                case_key,
                checklist_status="failed",
                phase="failed",
                status_message="Checklist extraction was cancelled.",
                error="Checklist extraction task cancelled.",
            )
        else:
            exc = task.exception()
            if exc is not None:
                self._update_status(
                    case_key,
                    checklist_status="failed",
                    phase="failed",
                    status_message="Checklist extraction failed.",
                    error=str(exc),
                )
            else:
                if self._status_by_case.get(case_key, ChecklistRunState(checklist_status="pending")).checklist_status != "ready":
                    self._update_status(
                        case_key,
                        checklist_status="ready",
                        phase="ready",
                        status_message="Checklist is ready.",
                        error=None,
                    )

        async with self._lock:
            current = self._in_flight.get(case_key)
            if current is task:
                self._in_flight.pop(case_key, None)

    async def _run_extraction(self, case_id: str, documents: List[DocumentReference]) -> EvidenceCollection:
        case_key = str(case_id)
        sorted_docs = sorted(documents, key=_document_sort_key)
        text_lookup = _build_text_lookup_from_references(case_id, sorted_docs)

        if self._global_lock.locked():
            producer.info("Checklist extraction queued behind active run", {"case_id": case_id})
            self._update_status(
                case_key,
                checklist_status="queued",
                phase="queued",
                status_message="Queued behind another checklist extraction run.",
                error=None,
            )

        async with self._global_lock:
            producer.info("Checklist extraction acquired global run lock", {"case_id": case_id})
            self._update_status(
                case_key,
                checklist_status="preprocessing",
                phase="preprocessing",
                status_message="Preparing documents for extraction.",
                error=None,
            )
            stored = self._store.get(case_id)
            if stored is not None:
                sanitized_items = _strip_sentence_ids_from_collection(stored.items, text_lookup)
                if sanitized_items != stored.items:
                    self._store.set(
                        case_id,
                        items=sanitized_items,
                        version=stored.version,
                    )
                self._update_status(
                    case_key,
                    checklist_status="ready",
                    phase="ready",
                    status_message="Checklist is ready.",
                    slurm_state=None,
                    error=None,
                )
                return _copy_collection(sanitized_items)

            try:
                result = await _run_extraction(
                    case_id,
                    sorted_docs,
                    text_lookup,
                    progress_callback=lambda event_type, event_data: self._handle_progress_event(
                        case_key,
                        event_type,
                        event_data,
                    ),
                )
                self._update_status(
                    case_key,
                    checklist_status="ready",
                    phase="ready",
                    status_message="Checklist extraction complete.",
                    slurm_state="COMPLETED",
                    error=None,
                )
                return _copy_collection(result)
            except Exception as exc:
                self._update_status(
                    case_key,
                    checklist_status="failed",
                    phase="failed",
                    status_message="Checklist extraction failed.",
                    error=str(exc),
                )
                raise

    def _handle_progress_event(self, case_key: str, event_type: str, data: Dict[str, Any]) -> None:
        if event_type == "started":
            self._update_status(
                case_key,
                checklist_status="pending",
                phase="starting",
                status_message="Controller started.",
                error=None,
            )
            return

        if event_type == "request_validated":
            max_steps = _coerce_optional_int(data.get("max_steps"))
            self._update_status(
                case_key,
                checklist_status="preprocessing",
                phase="request_validated",
                status_message="Request validated. Preparing case documents.",
                max_steps=max_steps if max_steps is not None else _UNSET,
                error=None,
            )
            return

        if event_type == "preprocess_started":
            self._update_status(
                case_key,
                checklist_status="preprocessing",
                phase="preprocessing",
                status_message="Preprocessing case documents.",
                error=None,
            )
            return

        if event_type == "preprocess_completed":
            self._update_status(
                case_key,
                checklist_status="waiting_resources",
                phase="waiting_resources",
                status_message="Preprocessing complete. Waiting for cluster resources.",
                error=None,
            )
            return

        if event_type == "document_map_ready":
            self._update_status(
                case_key,
                checklist_status="waiting_resources",
                phase="waiting_resources",
                status_message="Document map ready. Waiting for cluster resources.",
                error=None,
            )
            return

        if event_type == "slurm_submitted":
            self._update_status(
                case_key,
                checklist_status="waiting_resources",
                phase="waiting_resources",
                status_message="SLURM job submitted. Waiting for resources.",
                error=None,
            )
            return

        if event_type == "slurm_state":
            state = str(data.get("state") or "").strip().upper() or None
            if state == "PENDING":
                self._update_status(
                    case_key,
                    checklist_status="waiting_resources",
                    phase="waiting_resources",
                    slurm_state=state,
                    status_message="Waiting for cluster resources.",
                    error=None,
                )
                return
            if state == "RUNNING":
                self._update_status(
                    case_key,
                    checklist_status="running",
                    phase="running",
                    slurm_state=state,
                    status_message="Extraction is running on the cluster.",
                    error=None,
                )
                return
            if state == "COMPLETED":
                self._update_status(
                    case_key,
                    checklist_status="finalizing",
                    phase="finalizing",
                    slurm_state=state,
                    status_message="Cluster run complete. Finalizing checklist artifacts.",
                    error=None,
                )
                return
            if state:
                self._update_status(
                    case_key,
                    checklist_status="failed",
                    phase="failed",
                    slurm_state=state,
                    status_message=f"Cluster run ended in state {state}.",
                    error=f"Cluster run ended in state {state}.",
                )
            return

        if event_type == "step_completed":
            current_step = _coerce_optional_int(data.get("step"))
            self._update_status(
                case_key,
                checklist_status="running",
                phase="running",
                current_step=current_step if current_step is not None else _UNSET,
                status_message=(
                    f"Extraction step {current_step} completed."
                    if current_step is not None
                    else "Extraction progress updated."
                ),
                error=None,
            )
            return

        if event_type == "completed":
            self._update_status(
                case_key,
                checklist_status="finalizing",
                phase="finalizing",
                status_message="Controller completed. Finalizing checklist artifacts.",
                error=None,
            )
            return

        if event_type == "failed":
            error = str(data.get("error") or data.get("message") or "Cluster extraction failed.")
            self._update_status(
                case_key,
                checklist_status="failed",
                phase="failed",
                status_message="Checklist extraction failed.",
                error=error,
            )

    def _update_status(
        self,
        case_key: str,
        *,
        checklist_status: Any = _UNSET,
        status_message: Any = _UNSET,
        phase: Any = _UNSET,
        slurm_state: Any = _UNSET,
        current_step: Any = _UNSET,
        max_steps: Any = _UNSET,
        error: Any = _UNSET,
    ) -> None:
        current = self._status_by_case.get(case_key)
        if current is None:
            current = ChecklistRunState(checklist_status="pending")

        next_state = ChecklistRunState(
            checklist_status=current.checklist_status if checklist_status is _UNSET else str(checklist_status),
            status_message=current.status_message if status_message is _UNSET else status_message,
            phase=current.phase if phase is _UNSET else phase,
            slurm_state=current.slurm_state if slurm_state is _UNSET else slurm_state,
            current_step=current.current_step if current_step is _UNSET else current_step,
            max_steps=current.max_steps if max_steps is _UNSET else max_steps,
            error=current.error if error is _UNSET else error,
        )
        self._status_by_case[case_key] = next_state

    def _status_response(
        self,
        state: ChecklistRunState,
        *,
        document_checklists: Optional[EvidenceCollection] = None,
    ) -> ChecklistStatusResponse:
        return ChecklistStatusResponse(
            checklist_status=state.checklist_status,
            status_message=state.status_message,
            phase=state.phase,
            slurm_state=state.slurm_state,
            current_step=state.current_step,
            max_steps=state.max_steps,
            error=state.error,
            document_checklists=document_checklists,
        )


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


async def get_document_checklist_status(
    case_id: str, documents: List[DocumentReference]
) -> ChecklistStatusResponse:
    return await _EXTRACTION_RUN_MANAGER.get_status(case_id, documents)


async def start_document_checklist_extraction(
    case_id: str, documents: List[DocumentReference]
) -> ChecklistStatusResponse:
    return await _EXTRACTION_RUN_MANAGER.start_extraction(case_id, documents)


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
    return build_category_collection_from_collection(record.items)


def build_category_collection_from_collection(collection: EvidenceCollection) -> EvidenceCategoryCollection:
    sanitized_items = _strip_sentence_ids_from_collection(collection)
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
    case_id: str,
    documents: List[DocumentReference],
    text_lookup: Dict[int, str],
    progress_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
) -> EvidenceCollection:
    token = bind_event_case_id(case_id)
    try:
        engine = get_checklist_extraction_engine()
        producer.info(
            "Checklist extraction engine selected",
            {"case_id": case_id, "engine": engine.name},
        )
        result = await engine.run(case_id, documents, progress_callback=progress_callback)

        sanitized_items = _strip_sentence_ids_from_collection(result, text_lookup)
        _DOCUMENT_CHECKLIST_STORE.set(case_id, items=sanitized_items, version=_CHECKLIST_VERSION)
        return _copy_collection(sanitized_items)

    except Exception as exc:
        producer.error("Checklist extraction failed", {"case_id": case_id, "error": str(exc)})
        raise
    finally:
        reset_event_case_id(token)


def _coerce_optional_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return None
    return None
