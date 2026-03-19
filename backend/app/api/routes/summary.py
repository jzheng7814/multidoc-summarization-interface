from fastapi import APIRouter, BackgroundTasks

from app.schemas.summary import SummaryJobEnvelope, SummaryPromptResponse, SummaryRequest
from app.services import summary as summary_service

router = APIRouter(prefix="/cases", tags=["cases"])


@router.post("/{case_id}/summary", response_model=SummaryJobEnvelope)
async def start_summary_job(
    case_id: str,
    request: SummaryRequest,
    background_tasks: BackgroundTasks,
) -> SummaryJobEnvelope:
    job = await summary_service.create_summary_job(case_id, request, background_tasks)
    return SummaryJobEnvelope(job=job)


@router.get("/{case_id}/summary/{job_id}", response_model=SummaryJobEnvelope)
async def get_summary_job(case_id: str, job_id: str) -> SummaryJobEnvelope:
    job = await summary_service.get_summary_job(case_id, job_id)
    return SummaryJobEnvelope(job=job)


@router.get("/summary/prompt", response_model=SummaryPromptResponse)
async def get_summary_prompt() -> SummaryPromptResponse:
    prompt = summary_service.get_default_summary_prompt()
    return SummaryPromptResponse(prompt=prompt)
