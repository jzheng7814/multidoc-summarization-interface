from __future__ import annotations

import asyncio
import colorsys
from datetime import date as date_type, datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, cast
import uuid

from fastapi import BackgroundTasks, HTTPException, UploadFile

from app.core.config import get_settings
from app.data.run_store import SqlRunStore, StoredRun
from app.eventing import get_event_producer
from app.schemas.checklists import (
    EvidenceCategory,
    EvidenceCategoryCollection,
    EvidenceCategoryValue,
    EvidenceCollection,
    EvidenceItem,
    EvidencePointer,
)
from app.schemas.documents import Document, DocumentReference, UploadDocumentsManifest
from app.schemas.runs import (
    RunDefaultConfigResponse,
    RunCreateResponse,
    RunDocumentMetadata,
    RunExtractionConfig,
    RunExtractionStatusEnvelope,
    RunStageStatus,
    RunSummaryConfig,
    RunSummaryStatusEnvelope,
    WorkflowStage,
)
from app.schemas.summary import SummaryRequest
from app.services.checklist_engines import get_checklist_extraction_engine
from app.services.cluster_checklist_spec import validate_cluster_checklist_spec_payload
from app.services.cluster_focus_context import load_cluster_focus_context_template, render_cluster_focus_context_template
from app.services.cluster_queue import get_cluster_run_lock
from app.services.summary_engines import SummaryRunInput, get_summary_generation_engine
from app.services.summary_focus_context import load_default_summary_focus_context, render_summary_focus_context_template

producer = get_event_producer(__name__)
settings = get_settings()
_run_store = SqlRunStore()
_cluster_queue_lock = get_cluster_run_lock()
_start_lock = asyncio.Lock()
_WORKFLOW_STAGE_VALUES = {"setup", "extraction_wait", "review", "summary_wait", "workspace"}

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


def create_run_from_documents(
    *,
    source_type: str,
    title: str,
    documents: Sequence[Document],
) -> RunCreateResponse:
    run_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    extraction_config = _default_extraction_config()
    summary_config = _default_summary_config()
    _run_store.create_run(
        run_id=run_id,
        source_type=source_type,
        title=title,
        created_at=created_at,
        workflow_stage="setup",
        documents=list(documents),
        extraction_config=extraction_config,
        summary_config=summary_config,
    )
    stored = _require_run(run_id)
    return _to_run_response(stored)


def create_empty_run() -> RunCreateResponse:
    return create_run_from_documents(
        source_type="new_run",
        title="Untitled Run",
        documents=[],
    )


async def create_run_from_upload(manifest: UploadDocumentsManifest, files: List[UploadFile]) -> RunCreateResponse:
    title = manifest.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Run title is required.")
    documents = await _parse_uploaded_documents(manifest, files)
    return create_run_from_documents(
        source_type="manual_upload",
        title=title,
        documents=documents,
    )


async def update_run_from_upload(run_id: str, manifest: UploadDocumentsManifest, files: List[UploadFile]) -> RunCreateResponse:
    run = _require_run(run_id)
    _assert_run_not_active(run)

    title = manifest.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Run title is required.")
    documents = await _parse_uploaded_documents(manifest, files)
    _replace_run_documents(
        run,
        source_type="manual_upload",
        title=title,
        documents=documents,
    )
    return get_run(run_id)


def get_run(run_id: str) -> RunCreateResponse:
    return _to_run_response(_require_run(run_id))


def update_workflow_stage(run_id: str, workflow_stage: WorkflowStage) -> RunCreateResponse:
    run = _require_run(run_id)
    normalized_stage = _normalize_workflow_stage(workflow_stage)
    if run.summary_status in {"queued", "running"} and normalized_stage != "summary_wait":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Run '{run.id}' has active summary status '{run.summary_status}'. "
                "workflow_stage cannot be changed away from summary_wait."
            ),
        )
    if run.extraction_status in {"queued", "running"} and normalized_stage != "extraction_wait":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Run '{run.id}' has active extraction status '{run.extraction_status}'. "
                "workflow_stage cannot be changed away from extraction_wait."
            ),
        )
    if normalized_stage == "workspace" and run.summary_status != "succeeded":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Run '{run.id}' cannot move to workspace because summary_status is "
                f"'{run.summary_status}' (expected succeeded)."
            ),
        )
    if normalized_stage == "review" and run.extraction_status != "succeeded":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Run '{run.id}' cannot move to review because extraction_status is "
                f"'{run.extraction_status}' (expected succeeded)."
            ),
        )
    if normalized_stage == "summary_wait" and run.summary_status not in {"queued", "running"}:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Run '{run.id}' cannot move to summary_wait because summary_status is "
                f"'{run.summary_status}' (expected queued or running)."
            ),
        )
    if normalized_stage == "extraction_wait" and run.extraction_status not in {"queued", "running"}:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Run '{run.id}' cannot move to extraction_wait because extraction_status is "
                f"'{run.extraction_status}' (expected queued or running)."
            ),
        )
    _set_workflow_stage(run.id, normalized_stage)
    return get_run(run.id)


def get_default_configs() -> RunDefaultConfigResponse:
    return RunDefaultConfigResponse(
        extraction_config=RunExtractionConfig.model_validate(_default_extraction_config()),
        summary_config=RunSummaryConfig.model_validate(_default_summary_config()),
    )


def get_run_documents(run_id: str) -> List[Document]:
    return list(_require_run(run_id).documents)


def get_extraction_config(run_id: str) -> RunExtractionConfig:
    run = _require_run(run_id)
    return _parse_extraction_config(run.extraction_config)


def update_extraction_config(run_id: str, config: RunExtractionConfig) -> RunExtractionConfig:
    normalized = _normalize_extraction_config(config)
    _run_store.update_extraction_config(run_id, normalized)
    return _parse_extraction_config(normalized)


def get_summary_config(run_id: str) -> RunSummaryConfig:
    run = _require_run(run_id)
    return _parse_summary_config(run.summary_config)


def update_summary_config(run_id: str, config: RunSummaryConfig) -> RunSummaryConfig:
    normalized = config.model_dump(mode="json", by_alias=False)
    _run_store.update_summary_config(run_id, normalized)
    return _parse_summary_config(normalized)


async def start_extraction(run_id: str, background_tasks: BackgroundTasks, config: Optional[RunExtractionConfig]) -> RunExtractionStatusEnvelope:
    async with _start_lock:
        run = _require_run(run_id)
        if config is not None:
            normalized_config = _normalize_extraction_config(config)
            _run_store.update_extraction_config(run_id, normalized_config)
            run = _require_run(run_id)

        if run.extraction_status in {"queued", "running"}:
            return get_extraction_status(run_id)
        if not run.documents:
            raise HTTPException(
                status_code=409,
                detail=f"Run '{run_id}' has no documents. Load documents before starting extraction.",
            )

        _run_store.reset_for_extraction_start(run_id)

        _run_store.update_extraction_state(
            run_id,
            status="queued",
            error=None,
            progress={"phase": "queued", "event_type": "queued"},
        )
        _set_workflow_stage(run_id, "extraction_wait")
        background_tasks.add_task(_run_extraction_job, run_id)

    return get_extraction_status(run_id)


async def _run_extraction_job(run_id: str) -> None:
    if settings.cluster_checklist_strategy != "individual":
        message = "Run-centric extraction configuration requires MULTI_DOCUMENT_CLUSTER_CHECKLIST_STRATEGY=individual."
        _run_store.update_extraction_state(
            run_id,
            status="failed",
            error=message,
            progress={"phase": "failed", "event_type": "failed", "error": message},
        )
        _set_workflow_stage(run_id, "setup")
        return

    run = _require_run(run_id)
    extraction_config = _parse_extraction_config(run.extraction_config)

    doc_refs = _documents_to_references(run.documents)
    focus_context = render_cluster_focus_context_template(
        extraction_config.focus_context,
        {"RUN_TITLE": run.title},
    )
    checklist_spec = extraction_config.checklist_spec.model_dump(mode="json", by_alias=False)

    if _cluster_queue_lock.locked():
        _run_store.update_extraction_state(
            run_id,
            status="queued",
            error=None,
            progress={"phase": "queued", "event_type": "queued"},
        )

    async with _cluster_queue_lock:
        _run_store.update_extraction_state(
            run_id,
            status="running",
            error=None,
            progress={"phase": "starting", "event_type": "starting"},
        )

        try:
            engine = get_checklist_extraction_engine()
            result = await engine.run(
                run_id,
                run.id,
                doc_refs,
                progress_callback=lambda event_type, data: _handle_extraction_progress(run_id, event_type, data),
                checklist_spec=checklist_spec,
                focus_context=focus_context,
                run_title=run.title,
            )
            latest_run = _require_run(run_id)
            _run_store.store_extraction_result(
                run_id,
                extraction_result=result.collection.model_dump(mode="json", by_alias=False),
                remote_run_id=result.run_id,
                remote_job_id=result.job_id or latest_run.extraction_remote_job_id,
                remote_output_dir=result.output_dir or latest_run.extraction_remote_output_dir,
                manifest_path=result.manifest_path,
                result_payload_path=result.result_payload_path,
                checklist_ndjson_path=result.checklist_ndjson_path,
            )
            _set_workflow_stage(run_id, "review")
        except Exception as exc:  # pylint: disable=broad-except
            _run_store.update_extraction_state(
                run_id,
                status="failed",
                error=str(exc),
                progress={"phase": "failed", "event_type": "failed", "error": str(exc)},
            )
            _set_workflow_stage(run_id, "setup")
            producer.error("Extraction run failed", {"run_id": run_id, "error": str(exc)})


async def start_summary(run_id: str, background_tasks: BackgroundTasks, config: Optional[RunSummaryConfig]) -> RunSummaryStatusEnvelope:
    async with _start_lock:
        run = _require_run(run_id)
        if config is not None:
            normalized_config = config.model_dump(mode="json", by_alias=False)
            _run_store.update_summary_config(run_id, normalized_config)
            run = _require_run(run_id)

        if run.summary_status in {"queued", "running"}:
            return get_summary_status(run_id)

        if not run.extraction_result:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Summary generation requires completed extraction results for run '{run_id}'. "
                    "Run extraction first."
                ),
            )

        _run_store.reset_for_summary_start(run_id)
        _run_store.update_summary_state(
            run_id,
            status="queued",
            error=None,
            progress={"phase": "queued", "event_type": "queued"},
        )
        _set_workflow_stage(run_id, "summary_wait")
        background_tasks.add_task(_run_summary_job, run_id)

    return get_summary_status(run_id)


async def _run_summary_job(run_id: str) -> None:
    run = _require_run(run_id)
    summary_config = _parse_summary_config(run.summary_config)
    extraction_config = _parse_extraction_config(run.extraction_config)

    if not run.extraction_result:
        raise RuntimeError(f"Run '{run_id}' is missing extraction result payload.")

    checklist_collection = EvidenceCollection.model_validate(run.extraction_result)
    checklist_definitions = {
        item.key: item.description
        for item in extraction_config.checklist_spec.checklist_items
    }
    focus_context = render_summary_focus_context_template(
        summary_config.focus_context,
        {"RUN_TITLE": run.title.strip()},
    )
    summary_request = SummaryRequest(
        focus_context=focus_context,
        reasoning_effort=summary_config.reasoning_effort,
        max_steps=summary_config.max_steps,
    )

    if _cluster_queue_lock.locked():
        _run_store.update_summary_state(
            run_id,
            status="queued",
            error=None,
            progress={"phase": "queued", "event_type": "queued"},
        )

    async with _cluster_queue_lock:
        _run_store.update_summary_state(
            run_id,
            status="running",
            error=None,
            progress={"phase": "starting", "event_type": "starting"},
        )

        try:
            engine = get_summary_generation_engine()
            run_input = SummaryRunInput(
                backend_run_id=run_id,
                corpus_id=run.id,
                run_title=run.title,
                documents=run.documents,
                checklist_collection=checklist_collection,
                checklist_definitions=checklist_definitions,
                request=summary_request,
            )
            result = await engine.run(
                run_input,
                progress_callback=lambda event_type, data: _handle_summary_progress(run_id, event_type, data),
            )
            latest_run = _require_run(run_id)
            _run_store.store_summary_result(
                run_id,
                summary_text=result.summary_text,
                summary_result={
                    "run_id": result.run_id,
                    "job_id": result.job_id,
                    "completion_stats": result.completion_stats,
                    "result_payload_path": result.result_payload_path,
                    "manifest_path": result.manifest_path,
                    "summary_path": result.summary_path,
                },
                remote_run_id=result.run_id,
                remote_job_id=result.job_id or latest_run.summary_remote_job_id,
                remote_output_dir=latest_run.summary_remote_output_dir,
                manifest_path=result.manifest_path,
                result_payload_path=result.result_payload_path,
                summary_path=result.summary_path,
            )
            _set_workflow_stage(run_id, "workspace")
        except Exception as exc:  # pylint: disable=broad-except
            _run_store.update_summary_state(
                run_id,
                status="failed",
                error=str(exc),
                progress={"phase": "failed", "event_type": "failed", "error": str(exc)},
            )
            _set_workflow_stage(run_id, "review")
            producer.error("Summary run failed", {"run_id": run_id, "error": str(exc)})


def get_extraction_status(run_id: str) -> RunExtractionStatusEnvelope:
    run = _require_run(run_id)
    progress = run.extraction_progress or {}
    stage = RunStageStatus(
        status=run.extraction_status,
        phase=_coerce_str(progress.get("phase")),
        event_type=_coerce_str(progress.get("event_type")),
        slurm_state=_coerce_str(progress.get("slurm_state")),
        item_index=_coerce_int(progress.get("item_index")),
        items_total=_coerce_int(progress.get("items_total")),
        config_name=_coerce_str(progress.get("config_name")),
        tool_name=_coerce_str(progress.get("tool_name")),
        tool_success=_coerce_bool(progress.get("tool_success")),
        current_step=_coerce_int(progress.get("current_step")),
        max_steps=_coerce_int(progress.get("max_steps")),
        error=run.extraction_error,
        remote_run_id=run.extraction_remote_run_id,
        remote_job_id=run.extraction_remote_job_id,
    )
    return RunExtractionStatusEnvelope(run_id=run.id, extraction=stage)


def get_summary_status(run_id: str) -> RunSummaryStatusEnvelope:
    run = _require_run(run_id)
    progress = run.summary_progress or {}
    stage = RunStageStatus(
        status=run.summary_status,
        phase=_coerce_str(progress.get("phase")),
        event_type=_coerce_str(progress.get("event_type")),
        slurm_state=_coerce_str(progress.get("slurm_state")),
        item_index=_coerce_int(progress.get("item_index")),
        items_total=_coerce_int(progress.get("items_total")),
        config_name=_coerce_str(progress.get("config_name")),
        tool_name=_coerce_str(progress.get("tool_name")),
        tool_success=_coerce_bool(progress.get("tool_success")),
        current_step=_coerce_int(progress.get("current_step")),
        max_steps=_coerce_int(progress.get("max_steps")),
        error=run.summary_error,
        remote_run_id=run.summary_remote_run_id,
        remote_job_id=run.summary_remote_job_id,
    )
    return RunSummaryStatusEnvelope(run_id=run.id, summary=stage, summary_text=run.summary_text)


def get_checklist_categories(run_id: str) -> EvidenceCategoryCollection:
    run = _require_run(run_id)
    if not run.extraction_result:
        raise HTTPException(status_code=409, detail=f"Checklist is not ready for run '{run_id}'.")

    extraction_config = _parse_extraction_config(run.extraction_config)
    ordered_keys = [item.key for item in extraction_config.checklist_spec.checklist_items]
    collection = EvidenceCollection.model_validate(run.extraction_result)

    categories: Dict[str, EvidenceCategory] = {}
    counters: Dict[str, int] = {}

    for index, key in enumerate(ordered_keys):
        categories[key] = EvidenceCategory(
            id=key,
            label=key,
            color=_build_distinct_color(index),
            values=[],
        )
        counters[key] = 0

    for item in collection.items:
        key = str(item.bin_id)
        if key not in categories:
            categories[key] = EvidenceCategory(
                id=key,
                label=key,
                color=_build_distinct_color(len(categories)),
                values=[],
            )
            counters[key] = 0

        index = counters[key]
        counters[key] += 1
        ev = item.evidence
        categories[key].values.append(
            EvidenceCategoryValue(
                id=f"ai::{key}::{index}",
                value=item.value,
                text=item.value,
                document_id=ev.document_id,
                start_offset=ev.start_offset,
                end_offset=ev.end_offset,
            )
        )

    ordered_ids = list(ordered_keys)
    for key in categories.keys():
        if key not in ordered_ids:
            ordered_ids.append(key)

    return EvidenceCategoryCollection(categories=[categories[key] for key in ordered_ids])


def update_checklist_categories(run_id: str, payload: EvidenceCategoryCollection) -> EvidenceCategoryCollection:
    run = _require_run(run_id)
    if run.extraction_status != "succeeded" or not run.extraction_result:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Checklist edits are only allowed after extraction completes for run '{run_id}' "
                "(status must be succeeded)."
            ),
        )
    if run.summary_status in {"queued", "running"}:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Checklist edits are no longer allowed after summary has started for run '{run_id}' "
                f"(summary_status={run.summary_status})."
            ),
        )

    updated = _categories_to_evidence_collection(run, payload)
    _run_store.update_extraction_result(
        run_id,
        extraction_result=updated.model_dump(mode="json", by_alias=False),
    )
    return get_checklist_categories(run_id)


def _categories_to_evidence_collection(run: StoredRun, payload: EvidenceCategoryCollection) -> EvidenceCollection:
    document_lookup = {int(doc.id): doc for doc in run.documents}
    items: List[EvidenceItem] = []

    for category in payload.categories:
        category_id = str(category.id).strip()
        if not category_id:
            raise HTTPException(status_code=400, detail="Checklist category id cannot be empty.")

        for value in category.values:
            text = str(value.text or value.value or "").strip()
            if not text:
                raise HTTPException(
                    status_code=400,
                    detail=f"Checklist item in category '{category_id}' must include non-empty text.",
                )

            document_id = value.document_id
            if document_id is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"Checklist item '{text}' in category '{category_id}' is missing documentId.",
                )
            document = document_lookup.get(document_id)
            if document is None:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Checklist item '{text}' in category '{category_id}' references unknown "
                        f"document {document_id} for run '{run.id}'."
                    ),
                )

            start_offset = value.start_offset
            end_offset = value.end_offset
            if start_offset is None or end_offset is None or end_offset <= start_offset:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Checklist item '{text}' in category '{category_id}' has invalid offsets: "
                        f"start={start_offset}, end={end_offset}."
                    ),
                )
            if end_offset > len(document.content):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Checklist item '{text}' in category '{category_id}' has offsets outside "
                        f"document {document_id} bounds."
                    ),
                )

            items.append(
                EvidenceItem(
                    bin_id=category_id,
                    value=text,
                    evidence=EvidencePointer(
                        document_id=document_id,
                        start_offset=start_offset,
                        end_offset=end_offset,
                    ),
                )
            )

    return EvidenceCollection(items=items)


def _handle_extraction_progress(run_id: str, event_type: str, data: Dict[str, Any]) -> None:
    progress = {
        "event_type": event_type,
        "phase": event_type,
        "slurm_state": _coerce_str(data.get("state")),
        "item_index": _coerce_int(data.get("item_index")),
        "items_total": _coerce_int(data.get("items_total")),
        "config_name": _coerce_str(data.get("config_name")),
        "tool_name": _coerce_str(data.get("tool_name")),
        "tool_success": _coerce_bool(data.get("success")),
        "current_step": _coerce_int(data.get("step")),
        "max_steps": _coerce_int(data.get("max_steps")),
    }
    remote_run_id = _coerce_str(data.get("run_id"))
    remote_job_id = _coerce_str(data.get("job_id"))
    output_dir = _coerce_str(data.get("output_dir"))

    _run_store.update_extraction_state(
        run_id,
        status="running",
        error=None,
        progress=progress,
        remote_run_id=remote_run_id,
        remote_job_id=remote_job_id,
        remote_output_dir=output_dir,
    )


def _handle_summary_progress(run_id: str, event_type: str, data: Dict[str, Any]) -> None:
    progress = {
        "event_type": event_type,
        "phase": event_type,
        "slurm_state": _coerce_str(data.get("state")),
        "item_index": _coerce_int(data.get("item_index")),
        "items_total": _coerce_int(data.get("items_total")),
        "config_name": _coerce_str(data.get("config_name")),
        "tool_name": _coerce_str(data.get("tool_name")),
        "tool_success": _coerce_bool(data.get("success")),
        "current_step": _coerce_int(data.get("step")),
        "max_steps": _coerce_int(data.get("max_steps")),
    }
    remote_run_id = _coerce_str(data.get("run_id"))
    remote_job_id = _coerce_str(data.get("job_id"))
    output_dir = _coerce_str(data.get("output_dir"))

    _run_store.update_summary_state(
        run_id,
        status="running",
        error=None,
        progress=progress,
        remote_run_id=remote_run_id,
        remote_job_id=remote_job_id,
        remote_output_dir=output_dir,
    )


async def _parse_uploaded_documents(manifest: UploadDocumentsManifest, files: List[UploadFile]) -> List[Document]:
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

    output: List[Document] = []
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

        title = metadata.name.strip()
        if not title:
            raise HTTPException(status_code=400, detail=f"Document #{index} is missing a document name.")

        date_text = _normalize_upload_date(metadata.date, index)
        doc_type = _resolve_upload_document_type(metadata.type, metadata.type_other, index)

        output.append(
            Document(
                id=index,
                title=title,
                type=doc_type,
                description=f"Uploaded file {filename}",
                source="upload",
                date=date_text,
                is_docket=False,
                content=content,
            )
        )

    return _sort_documents(output)


def _documents_to_references(documents: Sequence[Document]) -> List[DocumentReference]:
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


def _default_extraction_config() -> Dict[str, Any]:
    strategy = settings.cluster_checklist_strategy
    if strategy != "individual":
        raise RuntimeError(
            "Run-centric extraction configuration requires MULTI_DOCUMENT_CLUSTER_CHECKLIST_STRATEGY=individual."
        )

    from app.services.cluster_checklist_spec import load_cluster_checklist_spec

    checklist_spec = load_cluster_checklist_spec(
        settings.cluster_checklist_spec_path,
        strategy="individual",
    )
    focus_context = load_cluster_focus_context_template(settings)

    config = {
        "focus_context": focus_context,
        "checklist_spec": checklist_spec,
    }
    normalized = _normalize_extraction_config(RunExtractionConfig.model_validate(config))
    return normalized


def _default_summary_config() -> Dict[str, Any]:
    config = RunSummaryConfig(
        focus_context=load_default_summary_focus_context(settings),
        reasoning_effort=settings.cluster_summary_reasoning_effort,
        max_steps=int(settings.cluster_summary_max_steps),
    )
    return config.model_dump(mode="json", by_alias=False)


def _normalize_extraction_config(config: RunExtractionConfig) -> Dict[str, Any]:
    payload = config.model_dump(mode="json", by_alias=False)
    raw_spec = payload.get("checklist_spec")
    if not isinstance(raw_spec, dict):
        raise RuntimeError("Extraction config checklist_spec must be an object.")
    normalized_spec = validate_cluster_checklist_spec_payload(raw_spec, strategy="individual")
    return {
        "focus_context": config.focus_context.strip(),
        "checklist_spec": normalized_spec,
    }


def _parse_extraction_config(raw_config: Dict[str, Any]) -> RunExtractionConfig:
    config = RunExtractionConfig.model_validate(raw_config)
    normalized = _normalize_extraction_config(config)
    return RunExtractionConfig.model_validate(normalized)


def _parse_summary_config(raw_config: Dict[str, Any]) -> RunSummaryConfig:
    return RunSummaryConfig.model_validate(raw_config)


def _to_run_response(run: StoredRun) -> RunCreateResponse:
    extraction_config = _parse_extraction_config(run.extraction_config)
    summary_config = _parse_summary_config(run.summary_config)
    documents = [
        RunDocumentMetadata(
            id=doc.id,
            title=doc.title,
            type=doc.type,
            source=doc.source,
            date=doc.date,
            ecf_number=doc.ecf_number,
            is_docket=doc.is_docket,
        )
        for doc in run.documents
    ]
    return RunCreateResponse(
        run_id=run.id,
        source_type=run.source_type,
        title=run.title,
        created_at=run.created_at,
        extraction_status=run.extraction_status,
        summary_status=run.summary_status,
        workflow_stage=_normalize_workflow_stage(run.workflow_stage),
        extraction_config=extraction_config,
        summary_config=summary_config,
        documents=documents,
    )


def _require_run(run_id: str) -> StoredRun:
    normalized = str(run_id).strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="run_id is required.")
    run = _run_store.get_run(normalized)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{normalized}' not found.")
    if run.extraction_config is None or run.summary_config is None:
        raise HTTPException(status_code=500, detail=f"Run '{normalized}' is missing required run configuration.")
    return run


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _sort_documents(documents: List[Document]) -> List[Document]:
    def _sort_key(document: Document) -> tuple:
        if document.is_docket:
            return (0, document.id)
        date_value = _parse_date(document.date)
        if date_value is None:
            return (1, 1, 0, document.id)
        return (1, 0, date_value, document.id)

    return sorted(list(documents), key=_sort_key)


def _assert_run_not_active(run: StoredRun) -> None:
    if run.extraction_status in {"queued", "running"}:
        raise HTTPException(
            status_code=409,
            detail=f"Run '{run.id}' is actively running extraction (status={run.extraction_status}).",
        )
    if run.summary_status in {"queued", "running"}:
        raise HTTPException(
            status_code=409,
            detail=f"Run '{run.id}' is actively running summary (status={run.summary_status}).",
        )


def _replace_run_documents(
    run: StoredRun,
    *,
    source_type: str,
    title: str,
    documents: Sequence[Document],
) -> None:
    _run_store.create_run(
        run_id=run.id,
        source_type=source_type,
        title=title,
        created_at=run.created_at,
        workflow_stage="setup",
        documents=list(documents),
        extraction_config=run.extraction_config,
        summary_config=run.summary_config,
    )


def _normalize_workflow_stage(value: Any) -> WorkflowStage:
    text = str(value).strip()
    if text not in _WORKFLOW_STAGE_VALUES:
        raise HTTPException(status_code=400, detail=f"Unsupported workflow_stage '{text}'.")
    return cast(WorkflowStage, text)


def _set_workflow_stage(run_id: str, workflow_stage: WorkflowStage) -> None:
    normalized = _normalize_workflow_stage(workflow_stage)
    _run_store.update_workflow_stage(run_id, normalized)


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


def _resolve_upload_document_type(raw_type: str, raw_type_other: Optional[str], index: int) -> str:
    chosen = (raw_type or "").strip()
    if not chosen:
        raise HTTPException(status_code=400, detail=f"Document #{index} is missing a document type.")

    if chosen == "Other":
        custom = (raw_type_other or "").strip()
        if not custom:
            raise HTTPException(
                status_code=400,
                detail=f"Document #{index} selected type 'Other' but did not provide typeOther.",
            )
        return custom

    if chosen not in _MANUAL_UPLOAD_DOCUMENT_TYPE_SET:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Document #{index} has unsupported document type '{chosen}'. "
                "Use one of the configured options or choose 'Other'."
            ),
        )
    return chosen


def _build_distinct_color(index: int) -> str:
    hue = ((index * 137.508) % 360) / 360.0
    red, green, blue = colorsys.hls_to_rgb(hue, 0.50, 0.62)
    return f"#{round(red * 255):02X}{round(green * 255):02X}{round(blue * 255):02X}"


def _coerce_str(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _coerce_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "1", "yes", "y"}:
            return True
        if text in {"false", "0", "no", "n"}:
            return False
    return None


def _coerce_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return int(stripped)
        except ValueError:
            return None
    return None
