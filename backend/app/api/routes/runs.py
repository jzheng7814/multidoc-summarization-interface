from __future__ import annotations

from typing import List

from fastapi import APIRouter, BackgroundTasks, Body, File, Form, HTTPException, UploadFile
from pydantic import ValidationError

from app.schemas.checklists import EvidenceCategoryCollection
from app.schemas.documents import UploadDocumentsManifest
from app.schemas.runs import (
    RunCreateFromCaseIdRequest,
    RunCreateResponse,
    RunDefaultConfigResponse,
    RunDocumentPayload,
    RunExtractionConfig,
    RunExtractionStartRequest,
    RunExtractionStatusEnvelope,
    RunSummaryConfig,
    RunSummaryStartRequest,
    RunSummaryStatusEnvelope,
    RunWorkflowStageUpdateRequest,
)
from app.services import runs as run_service

router = APIRouter(prefix="/runs", tags=["runs"])


@router.post("", response_model=RunCreateResponse)
async def create_empty_run() -> RunCreateResponse:
    return run_service.create_empty_run()


@router.post("/from-case-id", response_model=RunCreateResponse)
async def create_run_from_case_id(request: RunCreateFromCaseIdRequest) -> RunCreateResponse:
    return run_service.create_run_from_case_id(request.case_id)


@router.post("/upload-documents", response_model=RunCreateResponse)
async def create_run_from_upload(
    manifest: str = Form(...),
    files: List[UploadFile] = File(...),
) -> RunCreateResponse:
    try:
        manifest_payload = UploadDocumentsManifest.model_validate_json(manifest)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="Invalid upload manifest payload.") from exc

    return await run_service.create_run_from_upload(manifest_payload, files)


@router.post("/{run_id}/from-case-id", response_model=RunCreateResponse)
async def update_run_from_case_id(run_id: str, request: RunCreateFromCaseIdRequest) -> RunCreateResponse:
    return run_service.update_run_from_case_id(run_id, request.case_id)


@router.post("/{run_id}/upload-documents", response_model=RunCreateResponse)
async def update_run_from_upload(
    run_id: str,
    manifest: str = Form(...),
    files: List[UploadFile] = File(...),
) -> RunCreateResponse:
    try:
        manifest_payload = UploadDocumentsManifest.model_validate_json(manifest)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="Invalid upload manifest payload.") from exc

    return await run_service.update_run_from_upload(run_id, manifest_payload, files)


@router.get("/defaults", response_model=RunDefaultConfigResponse)
async def get_run_defaults() -> RunDefaultConfigResponse:
    return run_service.get_default_configs()


@router.get("/{run_id}", response_model=RunCreateResponse)
async def get_run(run_id: str) -> RunCreateResponse:
    return run_service.get_run(run_id)


@router.put("/{run_id}/workflow-stage", response_model=RunCreateResponse)
async def update_workflow_stage(run_id: str, request: RunWorkflowStageUpdateRequest) -> RunCreateResponse:
    return run_service.update_workflow_stage(run_id, request.workflow_stage)


@router.get("/{run_id}/documents", response_model=List[RunDocumentPayload])
async def get_run_documents(run_id: str) -> List[RunDocumentPayload]:
    docs = run_service.get_run_documents(run_id)
    return [
        RunDocumentPayload(
            id=doc.id,
            title=doc.title,
            type=doc.type,
            description=doc.description,
            source=doc.source,
            date=doc.date,
            ecf_number=doc.ecf_number,
            is_docket=doc.is_docket,
            content=doc.content,
        )
        for doc in docs
    ]


@router.get("/{run_id}/extraction-config", response_model=RunExtractionConfig)
async def get_extraction_config(run_id: str) -> RunExtractionConfig:
    return run_service.get_extraction_config(run_id)


@router.put("/{run_id}/extraction-config", response_model=RunExtractionConfig)
async def update_extraction_config(run_id: str, config: RunExtractionConfig) -> RunExtractionConfig:
    return run_service.update_extraction_config(run_id, config)


@router.get("/{run_id}/summary-config", response_model=RunSummaryConfig)
async def get_summary_config(run_id: str) -> RunSummaryConfig:
    return run_service.get_summary_config(run_id)


@router.put("/{run_id}/summary-config", response_model=RunSummaryConfig)
async def update_summary_config(run_id: str, config: RunSummaryConfig) -> RunSummaryConfig:
    return run_service.update_summary_config(run_id, config)


@router.post("/{run_id}/extraction/start", response_model=RunExtractionStatusEnvelope)
async def start_extraction(
    run_id: str,
    background_tasks: BackgroundTasks,
    request: RunExtractionStartRequest = Body(default_factory=RunExtractionStartRequest),
) -> RunExtractionStatusEnvelope:
    return await run_service.start_extraction(run_id, background_tasks, request.extraction_config)


@router.get("/{run_id}/extraction/status", response_model=RunExtractionStatusEnvelope)
async def get_extraction_status(run_id: str) -> RunExtractionStatusEnvelope:
    return run_service.get_extraction_status(run_id)


@router.get("/{run_id}/checklist", response_model=EvidenceCategoryCollection)
async def get_run_checklist(run_id: str) -> EvidenceCategoryCollection:
    return run_service.get_checklist_categories(run_id)


@router.put("/{run_id}/checklist", response_model=EvidenceCategoryCollection)
async def update_run_checklist(run_id: str, payload: EvidenceCategoryCollection) -> EvidenceCategoryCollection:
    return run_service.update_checklist_categories(run_id, payload)


@router.post("/{run_id}/summary/start", response_model=RunSummaryStatusEnvelope)
async def start_summary(
    run_id: str,
    background_tasks: BackgroundTasks,
    request: RunSummaryStartRequest = Body(default_factory=RunSummaryStartRequest),
) -> RunSummaryStatusEnvelope:
    return await run_service.start_summary(run_id, background_tasks, request.summary_config)


@router.get("/{run_id}/summary/status", response_model=RunSummaryStatusEnvelope)
async def get_summary_status(run_id: str) -> RunSummaryStatusEnvelope:
    return run_service.get_summary_status(run_id)
