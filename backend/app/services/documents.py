from __future__ import annotations

import hashlib
from datetime import date as date_type, datetime
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional
import uuid

from fastapi import HTTPException, UploadFile

from app.core.config import get_settings
from app.data.case_document_store import CaseDocumentStore, SqlCaseDocumentStore
from app.eventing import get_event_producer
from app.schemas.documents import Document, DocumentMetadata, UploadDocumentsManifest, UploadManifestDocument
from app.services.clearinghouse import (
    ClearinghouseClient,
    ClearinghouseError,
    ClearinghouseNotConfigured,
    ClearinghouseNotFound,
)

producer = get_event_producer(__name__)

_settings = get_settings()
_CASE_STORE: CaseDocumentStore = SqlCaseDocumentStore()

MANUAL_UPLOAD_DOCUMENT_TYPES: List[str] = [
    "Complaint",
    "Opinion/Order",
    "Pleading/Motion/Brief",
    "Monitor/Expert/Receiver Report",
    "Settlement",
    "Docket",
    "Correspondence",
    "Declaration/Affidavit",
    "Discovery/FOIA Material",
    "FOIA Request",
    "Internal Memorandum",
    "Legislative Report",
    "Magistrate Report/Recommendation",
    "Statute/Ordinance/Regulation",
    "Executive Order",
    "Transcripts",
    "Justification Memo",
    "Notice Letter",
    "Findings Memo",
]
_MANUAL_UPLOAD_DOCUMENT_TYPE_SET = set(MANUAL_UPLOAD_DOCUMENT_TYPES)


class UploadedCaseResult:
    def __init__(self, case_id: str, reused: bool, document_count: int, signature: str) -> None:
        self.case_id = case_id
        self.reused = reused
        self.document_count = document_count
        self.signature = signature


def list_documents(case_id: str) -> List[Document]:
    normalized = _normalize_case_id(case_id)

    cached = _get_stored_documents(normalized)
    if cached is not None:
        producer.info("Serving stored documents", {"case_id": normalized})
        return cached

    producer.info("Fetching documents from Clearinghouse", {"case_id": normalized})
    try:
        documents, case_title = _fetch_remote_documents(normalized)
    except ClearinghouseNotConfigured as exc:
        producer.warning("Clearinghouse API key not configured", {"case_id": normalized})
        cached = _get_stored_documents(normalized)
        if cached:
            return cached
        raise HTTPException(
            status_code=503, detail="Clearinghouse API key has not been configured on the server."
        ) from exc
    except ClearinghouseNotFound as exc:
        cached = _get_stored_documents(normalized)
        if cached:
            return cached
        raise HTTPException(status_code=404, detail=f"Case '{normalized}' was not found on Clearinghouse.") from exc
    except ClearinghouseError as exc:
        producer.warning(
            "Clearinghouse request failed",
            {"case_id": normalized, "error": str(exc)},
        )
        cached = _get_stored_documents(normalized)
        if cached:
            return cached
        raise HTTPException(
            status_code=502, detail="Failed to retrieve documents from Clearinghouse. Please try again later."
        ) from exc

    ordered = _sort_documents(documents)
    _remember_documents(normalized, ordered, case_title)
    return _clone_documents(ordered)


async def upload_text_documents(manifest: UploadDocumentsManifest, files: List[UploadFile]) -> UploadedCaseResult:
    case_name = manifest.case_name.strip()
    if not case_name:
        raise HTTPException(status_code=400, detail="Case name is required.")
    if not files:
        raise HTTPException(status_code=400, detail="At least one .txt document must be uploaded.")
    if not manifest.documents:
        raise HTTPException(status_code=400, detail="At least one document manifest entry is required.")
    if len(files) != len(manifest.documents):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Manifest/document mismatch: received {len(manifest.documents)} manifest entries "
                f"for {len(files)} uploaded files."
            ),
        )

    processed: List[Dict[str, Any]] = []
    for index, (metadata, file) in enumerate(zip(manifest.documents, files), start=1):
        filename = (file.filename or "").strip()
        if not filename:
            raise HTTPException(status_code=400, detail=f"Document #{index} is missing an uploaded filename.")
        if not filename.lower().endswith(".txt"):
            raise HTTPException(status_code=400, detail=f"Unsupported file type for '{filename}'. Only .txt is allowed.")

        expected_filename = (metadata.file_name or "").strip()
        if expected_filename and expected_filename != filename:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Uploaded filename mismatch for document #{index}: "
                    f"manifest expected '{expected_filename}', got '{filename}'."
                ),
            )

        payload = await file.read()
        try:
            content = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"File '{filename}' is not valid UTF-8 text.",
            ) from exc

        resolved_title = metadata.name.strip()
        if not resolved_title:
            raise HTTPException(status_code=400, detail=f"Document #{index} is missing a document name.")

        resolved_date = _normalize_upload_date(metadata.date, index)
        resolved_type = _resolve_upload_document_type(metadata, index)
        processed.append(
            {
                "filename": filename,
                "content": content,
                "title": resolved_title,
                "date": resolved_date,
                "type": resolved_type,
            }
        )

    signature = _compute_upload_signature(case_name, processed)
    case_id = _CASE_STORE.next_negative_case_id()
    documents: List[Document] = []
    for index, item in enumerate(processed, start=1):
        documents.append(
            Document(
                id=index,
                title=item["title"],
                type=item["type"],
                description=f"Uploaded file {item['filename']}",
                source="upload",
                date=item["date"],
                content=item["content"],
            )
        )

    _remember_documents(case_id, documents, case_name, signature=signature)
    return UploadedCaseResult(
        case_id=case_id,
        reused=False,
        document_count=len(documents),
        signature=signature,
    )


def list_cached_documents(case_id: str) -> List[Document]:
    """Return cached/stored documents for a case without hitting external sources."""
    normalized = _normalize_case_id(case_id)
    cached = _get_stored_documents(normalized)
    if cached is not None:
        return _sort_documents(cached)
    return []


def get_document(case_id: str, document_id: str) -> Document:
    normalized = _normalize_case_id(case_id)
    documents = _get_stored_documents(normalized)
    if documents is None:
        documents = list_documents(normalized)
    for document in documents:
        if document.id == document_id:
            return document
    raise HTTPException(status_code=404, detail=f"Document '{document_id}' not found for case '{case_id}'")


def get_document_metadata(case_id: str) -> List[DocumentMetadata]:
    normalized = _normalize_case_id(case_id)
    documents = _get_stored_documents(normalized)
    if documents is None:
        documents = list_documents(normalized)
    return [
        DocumentMetadata(
            id=doc.id,
            title=doc.title,
            type=doc.type,
            description=doc.description,
            source=doc.source,
        )
        for doc in documents
    ]


def get_case_title(case_id: str) -> Optional[str]:
    """Return the cached case title if available."""
    normalized = _normalize_case_id(case_id)
    stored = _CASE_STORE.get(normalized)
    if stored is None:
        return None

    return stored.case_title


def _require_case_title(source: Optional[str], documents: Iterable[Document]) -> str:
    if isinstance(source, str) and source.strip():
        return source.strip()
    for doc in documents:
        if isinstance(doc.description, str) and doc.description.strip():
            return doc.description.strip()
        if isinstance(doc.title, str) and doc.title.strip():
            return doc.title.strip()
    raise HTTPException(status_code=500, detail="Case title could not be determined from the provided documents.")


def _fetch_remote_documents(case_id: str) -> tuple[List[Document], str]:
    client = _get_clearinghouse_client()
    documents, case_title = client.fetch_case_documents(case_id)
    resolved_title = _require_case_title(case_title, documents)
    return documents, resolved_title


@lru_cache
def _get_clearinghouse_client() -> ClearinghouseClient:
    api_key = _settings.clearinghouse_api_key
    if not api_key:
        raise ClearinghouseNotConfigured("Clearinghouse API key is not configured.")
    return ClearinghouseClient(api_key=api_key)


def _remember_documents(
    case_id: str,
    documents: Iterable[Document],
    case_title: str,
    *,
    signature: Optional[str] = None,
) -> None:
    try:
        _CASE_STORE.set(case_id, [doc.model_dump(mode="json") for doc in documents], case_title, signature=signature)
    except Exception:  # pylint: disable=broad-except
        producer.error("Failed to persist documents", {"case_id": case_id})


def _get_stored_documents(case_id: str) -> Optional[List[Document]]:
    stored = _CASE_STORE.get(case_id)
    if stored is None:
        return None

    documents: List[Document] = []
    for item in stored.documents:
        if isinstance(item, dict):
            working = dict(item)
            if "title" not in working and "name" in working:
                working["title"] = working.pop("name")
            if "id" in working and not isinstance(working["id"], int):
                try:
                    working["id"] = int(str(working["id"]).strip())
                except (TypeError, ValueError):
                    producer.warning(
                        "Unable to coerce cached document id to integer",
                        {"case_id": case_id, "document_id": working["id"]},
                    )
                    continue
            item = working
        documents.append(Document.model_validate(item))
    ordered = _sort_documents(documents)
    return _clone_documents(ordered)


def _clone_documents(documents: Iterable[Document]) -> List[Document]:
    return [Document.model_validate(doc.model_dump(mode="python")) for doc in documents]


def _normalize_case_id(case_id: str) -> str:
    try:
        return str(int(case_id))
    except (TypeError, ValueError):
        return str(case_id)


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _document_sort_key(document: Document) -> tuple:
    if document.is_docket:
        return (0, document.id)
    date_value = _parse_date(document.date)
    if date_value is None:
        return (1, 1, 0, document.id)
    return (1, 0, -date_value.timestamp(), document.id)


def _sort_documents(documents: List[Document]) -> List[Document]:
    return sorted(list(documents), key=_document_sort_key)


def _compute_upload_signature(case_name: str, documents: List[Dict[str, Any]]) -> str:
    # Upload dedupe is intentionally strict and always creates a new case id.
    # Include random entropy in signature so repeated uploads never collide on unique DB constraint.
    hasher = hashlib.sha256()
    hasher.update(case_name.encode("utf-8"))
    hasher.update(uuid.uuid4().hex.encode("ascii"))
    for entry in documents:
        payload = entry["content"].encode("utf-8")
        hasher.update(len(payload).to_bytes(8, byteorder="big", signed=False))
        hasher.update(payload)
        for field in ("title", "type", "date"):
            value = entry.get(field)
            normalized = "" if value is None else str(value)
            encoded = normalized.encode("utf-8")
            hasher.update(len(encoded).to_bytes(4, byteorder="big", signed=False))
            hasher.update(encoded)
    return hasher.hexdigest()


def _normalize_upload_date(value: Optional[str], index: int) -> str:
    if value is None:
        raise HTTPException(status_code=400, detail=f"Document #{index} is missing a filing date.")
    text = value.strip()
    if not text:
        raise HTTPException(status_code=400, detail=f"Document #{index} is missing a filing date.")
    try:
        parsed = date_type.fromisoformat(text)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Document #{index} has invalid date '{text}'. Expected YYYY-MM-DD.",
        ) from exc
    return parsed.isoformat()


def _resolve_upload_document_type(metadata: UploadManifestDocument, index: int) -> str:
    selected = metadata.type.strip()
    if not selected:
        raise HTTPException(status_code=400, detail=f"Document #{index} is missing a document type.")
    if selected == "Other":
        custom = (metadata.type_other or "").strip()
        if not custom:
            raise HTTPException(
                status_code=400,
                detail=f"Document #{index} selected 'Other' but did not provide a custom type.",
            )
        return custom
    if selected not in _MANUAL_UPLOAD_DOCUMENT_TYPE_SET:
        raise HTTPException(
            status_code=400,
            detail=f"Document #{index} has unsupported document type '{selected}'.",
        )
    return selected
