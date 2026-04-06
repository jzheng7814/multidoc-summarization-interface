from __future__ import annotations

import asyncio
import uuid
from typing import Dict

from fastapi import BackgroundTasks, HTTPException

from app.data.checklist_store import SqlDocumentChecklistStore
from app.eventing import get_event_producer
from app.schemas.summary import SummaryJob, SummaryJobStatus, SummaryRequest
from app.services.cluster_queue import get_cluster_run_lock
from app.services.documents import list_cached_documents
from app.services.summary_engines import SummaryRunInput, get_summary_generation_engine

producer = get_event_producer(__name__)

_summary_jobs: Dict[str, SummaryJob] = {}
_summary_jobs_lock = asyncio.Lock()
_cluster_queue_lock = get_cluster_run_lock()
_checklist_store = SqlDocumentChecklistStore()

DEFAULT_SUMMARY_PROMPT = (
    "You are drafting a grounded multi-document summary.\n"
    "Use source documents as primary authority, treat structured inputs as retrieval aids rather than ground truth, "
    "and follow any run-specific focus context for scope, target identity, and special constraints.\n"
)


def get_default_summary_prompt() -> str:
    return DEFAULT_SUMMARY_PROMPT


async def create_summary_job(case_id: str, request: SummaryRequest, background_tasks: BackgroundTasks) -> SummaryJob:
    cached_docs = list_cached_documents(case_id)
    if not cached_docs:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Summary generation requires cached local documents for case '{case_id}'. "
                "Load documents first."
            ),
        )
    if _checklist_store.get(case_id) is None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Summary generation requires a completed checklist for case '{case_id}'. "
                "Run checklist extraction first."
            ),
        )

    job_id = str(uuid.uuid4())
    job = SummaryJob(id=job_id, case_id=case_id, status=SummaryJobStatus.pending)
    async with _summary_jobs_lock:
        _summary_jobs[job_id] = job

    background_tasks.add_task(_run_summary_job, job_id, case_id, request)
    return job


async def _run_summary_job(job_id: str, case_id: str, request: SummaryRequest) -> None:
    if _cluster_queue_lock.locked():
        producer.info("Summary job queued behind another cluster run", {"job_id": job_id, "case_id": case_id})

    async with _cluster_queue_lock:
        await _update_job(job_id, status=SummaryJobStatus.running)

        try:
            stored = _checklist_store.get(case_id)
            if stored is None:
                raise RuntimeError(f"No checklist is available for case '{case_id}'.")
            cached_docs = list_cached_documents(case_id)
            if not cached_docs:
                raise RuntimeError(f"No cached documents are available for case '{case_id}'.")

            engine = get_summary_generation_engine()
            producer.info(
                "Summary generation engine selected",
                {"job_id": job_id, "case_id": case_id, "engine": engine.name},
            )
            checklist_collection = stored.items
            checklist_definitions = {item.bin_id: item.bin_id for item in checklist_collection.items}
            result = await engine.run(
                SummaryRunInput(
                    backend_run_id=job_id,
                    case_id=case_id,
                    case_title=None,
                    documents=cached_docs,
                    checklist_collection=checklist_collection,
                    checklist_definitions=checklist_definitions,
                    request=request,
                ),
                progress_callback=lambda event_type, event_data: _handle_cluster_progress(job_id, event_type, event_data),
            )
            await _update_job(
                job_id,
                status=SummaryJobStatus.succeeded,
                summary_text=result.summary_text,
                run_id=result.run_id,
                remote_job_id=result.job_id,
                error=None,
            )
        except Exception as exc:  # pylint: disable=broad-except
            producer.error(
                "Summary job failed",
                {
                    "job_id": job_id,
                    "case_id": case_id,
                    "error": str(exc),
                },
            )
            await _update_job(
                job_id,
                status=SummaryJobStatus.failed,
                error=str(exc),
            )


def _handle_cluster_progress(job_id: str, event_type: str, event_data: Dict[str, object]) -> None:
    updates: Dict[str, str] = {}

    if event_type == "started":
        run_id = event_data.get("run_id")
        if isinstance(run_id, str) and run_id.strip():
            updates["run_id"] = run_id.strip()

    if event_type == "slurm_submitted":
        remote_job_id = event_data.get("job_id")
        if isinstance(remote_job_id, str) and remote_job_id.strip():
            updates["remote_job_id"] = remote_job_id.strip()

    if not updates:
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    loop.create_task(_update_job(job_id, **updates))


async def _update_job(job_id: str, **updates) -> None:
    async with _summary_jobs_lock:
        job = _summary_jobs.get(job_id)
        if job is None:
            return
        _summary_jobs[job_id] = job.model_copy(update=updates)


async def get_summary_job(case_id: str, job_id: str) -> SummaryJob:
    async with _summary_jobs_lock:
        job = _summary_jobs.get(job_id)

    if job is None or str(job.case_id) != str(case_id):
        raise HTTPException(status_code=404, detail="Summary job not found")

    return job
