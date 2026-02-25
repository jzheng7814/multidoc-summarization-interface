from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import ValidationError

from app.eventing import get_event_producer
from app.schemas.documents import (
    DocumentListResponse,
    DocumentReference,
    UploadDocumentsManifest,
    UploadDocumentsResponse,
)
from app.schemas.checklists import EvidenceCollection
from app.services.checklists import get_document_checklists_if_cached
from app.services.documents import list_documents, upload_text_documents

router = APIRouter(prefix="/cases", tags=["cases"])
producer = get_event_producer(__name__)


@router.get("/{case_id}/documents", response_model=DocumentListResponse)
async def get_case_documents(case_id: str) -> DocumentListResponse:
    documents = list_documents(case_id)
    document_refs = [
        DocumentReference(
            id=doc.id,
            title=doc.title,
            type=doc.type,
            include_full_text=True,
            content=doc.content,
            ecf_number=doc.ecf_number,
            date=doc.date,
            is_docket=doc.is_docket,
        )
        for doc in documents
    ]

    document_checklists: Optional[EvidenceCollection] = None
    checklist_status = "empty" if not document_refs else "pending"

    if document_refs:
        try:
            cached = await get_document_checklists_if_cached(case_id, document_refs)
        except Exception:  # pylint: disable=broad-except
            producer.error("Unable to inspect checklist cache", {"case_id": case_id})
            cached = None

        if cached is not None:
            document_checklists = cached
            checklist_status = "cached"

    return DocumentListResponse(
        case_id=case_id,
        documents=documents,
        document_checklists=document_checklists,
        checklist_status=checklist_status,
    )


@router.post("/upload-documents", response_model=UploadDocumentsResponse)
async def upload_case_documents(
    manifest: str = Form(...),
    files: list[UploadFile] = File(...),
) -> UploadDocumentsResponse:
    try:
        manifest_payload = UploadDocumentsManifest.model_validate_json(manifest)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="Invalid upload manifest payload.") from exc

    result = await upload_text_documents(manifest_payload, files)
    return UploadDocumentsResponse(
        case_id=result.case_id,
        reused=result.reused,
        document_count=result.document_count,
        signature=result.signature,
    )
