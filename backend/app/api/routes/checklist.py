from typing import List

from fastapi import APIRouter, HTTPException

from app.eventing import get_event_producer
from app.schemas.checklists import EvidenceCategoryCollection, ChecklistStatusResponse
from app.schemas.documents import DocumentReference
from app.services import checklists as checklist_service
from app.services.documents import list_documents, list_cached_documents

router = APIRouter(prefix="/cases", tags=["checklists"])
producer = get_event_producer(__name__)


def _build_document_references(case_id: str) -> List[DocumentReference]:
    documents = list_documents(case_id)
    return [
        DocumentReference(
            id=doc.id,
            title=doc.title,
            type=doc.type,
            include_full_text=True,
            content=doc.content,
            date=doc.date,
            ecf_number=doc.ecf_number,
            is_docket=doc.is_docket,
        )
        for doc in documents
    ]


def _build_cached_document_references(case_id: str) -> List[DocumentReference]:
    documents = list_cached_documents(case_id)
    return [
        DocumentReference(
            id=doc.id,
            title=doc.title,
            type=doc.type,
            include_full_text=True,
            content=doc.content,
            date=doc.date,
            ecf_number=doc.ecf_number,
            is_docket=doc.is_docket,
        )
        for doc in documents
    ]


@router.get("/{case_id}/checklist", response_model=EvidenceCategoryCollection)
async def get_case_checklist(case_id: str) -> EvidenceCategoryCollection:
    document_refs = _build_cached_document_references(case_id)
    if not document_refs:
        raise HTTPException(
            status_code=409,
            detail=f"Checklist is not ready for case '{case_id}'. Start extraction first.",
        )

    cached = await checklist_service.get_document_checklists_if_cached(case_id, document_refs)
    if cached is None:
        raise HTTPException(
            status_code=409,
            detail=f"Checklist is not ready for case '{case_id}'.",
        )
    return checklist_service.build_category_collection_from_collection(cached)


@router.post("/{case_id}/checklist/start", response_model=ChecklistStatusResponse)
async def start_case_checklist(case_id: str) -> ChecklistStatusResponse:
    document_refs = _build_document_references(case_id)
    return await checklist_service.start_document_checklist_extraction(case_id, document_refs)


@router.get("/{case_id}/checklist/status", response_model=ChecklistStatusResponse)
async def get_checklist_status(case_id: str) -> ChecklistStatusResponse:
    document_refs = _build_cached_document_references(case_id)
    try:
        return await checklist_service.get_document_checklist_status(case_id, document_refs)
    except Exception:  # pylint: disable=broad-except
        producer.error("Failed to check checklist status", {"case_id": case_id})
        return ChecklistStatusResponse(
            checklist_status="error",
            status_message="Failed to fetch checklist status.",
            error="status_query_failed",
            document_checklists=None,
        )
