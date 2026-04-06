from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional, Protocol, Sequence

from app.core.config import Settings, get_settings
from app.schemas.checklists import EvidenceCollection
from app.schemas.documents import Document
from app.schemas.summary import SummaryRequest
from app.services.cluster_summary import ClusterSummaryResult, ClusterSummaryRunner, run_cluster_summary
from app.services.spoof_replay import (
    load_spoof_events,
    load_spoof_json,
    load_spoof_request_payload,
    replay_spoof_events,
    require_completed_terminal_event,
    resolve_spoof_fixture_dir,
    validate_fixture_case,
    validate_fixture_document_ids,
)

ProgressCallback = Callable[[str, Dict[str, Any]], None]


@dataclass(frozen=True)
class SummaryRunInput:
    backend_run_id: str
    case_id: str
    case_title: Optional[str]
    documents: Sequence[Document]
    checklist_collection: EvidenceCollection
    checklist_definitions: Mapping[str, str]
    request: SummaryRequest


class SummaryGenerationEngine(Protocol):
    name: str

    async def run(
        self,
        run_input: SummaryRunInput,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> ClusterSummaryResult:
        ...


class ClusterSummaryGenerationEngine:
    name = "cluster"

    async def run(
        self,
        run_input: SummaryRunInput,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> ClusterSummaryResult:
        return await run_cluster_summary(
            run_input.backend_run_id,
            run_input.case_id,
            case_title=run_input.case_title,
            documents=run_input.documents,
            checklist_collection=run_input.checklist_collection,
            checklist_definitions=run_input.checklist_definitions,
            request=run_input.request,
            progress_callback=progress_callback,
        )


class SpoofSummaryGenerationEngine:
    name = "spoof"

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self._settings = settings or get_settings()

    async def run(
        self,
        run_input: SummaryRunInput,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> ClusterSummaryResult:
        fixture_dir = resolve_spoof_fixture_dir(self._settings.cluster_spoof_summary_fixture_dir)
        request_payload = load_spoof_request_payload(fixture_dir)
        validate_fixture_case(run_input.case_id, request_payload, label="Spoof summary fixture")
        validate_fixture_document_ids(
            [document.id for document in run_input.documents],
            request_payload,
            label="Spoof summary fixture",
        )

        events = load_spoof_events(fixture_dir / "events.ndjson")
        terminal_event = await replay_spoof_events(
            events,
            progress_callback=progress_callback,
            delay_seconds=max(0.0, float(self._settings.cluster_spoof_event_delay_seconds)),
        )
        require_completed_terminal_event(terminal_event, label="Spoof summary fixture")

        summary_payload = load_spoof_json(fixture_dir / "summary.json")
        result_payload = load_spoof_json(fixture_dir / "result_payload.json")
        if not isinstance(summary_payload, dict):
            raise RuntimeError(f"Spoof summary fixture summary.json must be a JSON object: {fixture_dir}")
        if not isinstance(result_payload, dict):
            raise RuntimeError(f"Spoof summary fixture result_payload.json must be a JSON object: {fixture_dir}")

        runner = ClusterSummaryRunner()
        terminal_data = terminal_event.get("data")
        terminal_payload = dict(terminal_data) if isinstance(terminal_data, dict) else {}
        run_id = str(terminal_payload.get("run_id") or summary_payload.get("run_id") or "").strip()
        if not run_id:
            raise RuntimeError("Spoof summary fixture is missing run_id in terminal event and summary payload.")
        job_id = str(terminal_payload.get("job_id") or result_payload.get("job_id") or "").strip()
        if not job_id:
            raise RuntimeError("Spoof summary fixture is missing job_id in terminal event and result payload.")

        summary_text = runner._extract_summary_text(summary_payload, result_payload, run_input.case_id).strip()  # pylint: disable=protected-access
        summary_stats = result_payload.get("completion_stats")
        if not isinstance(summary_stats, dict):
            summary_stats = summary_payload.get("summary_stats")
        if not isinstance(summary_stats, dict):
            summary_stats = {}

        return ClusterSummaryResult(
            summary_text=summary_text,
            run_id=run_id,
            job_id=job_id,
            completion_stats=summary_stats,
            result_payload_path=str((fixture_dir / "result_payload.json").resolve()),
            manifest_path=str((fixture_dir / "manifest.json").resolve()),
            summary_path=str((fixture_dir / "summary.json").resolve()),
        )


_CLUSTER_ENGINE = ClusterSummaryGenerationEngine()


def get_summary_generation_engine() -> SummaryGenerationEngine:
    settings = get_settings()
    if settings.cluster_run_mode == "spoof":
        return SpoofSummaryGenerationEngine(settings)
    return _CLUSTER_ENGINE
