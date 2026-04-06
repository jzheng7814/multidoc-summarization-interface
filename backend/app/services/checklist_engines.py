from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Protocol

from app.core.config import Settings, get_settings
from app.schemas.documents import DocumentReference
from app.services.cluster_extraction import ClusterChecklistRunner, ClusterExtractionResult, run_cluster_extraction
from app.services.spoof_replay import (
    load_spoof_events,
    load_spoof_json,
    load_spoof_request_payload,
    replay_spoof_events,
    require_completed_terminal_event,
    resolve_spoof_fixture_dir,
    validate_fixture_corpus,
    validate_fixture_document_ids,
)


class ChecklistExtractionEngine(Protocol):
    name: str

    async def run(
        self,
        backend_run_id: str,
        corpus_id: str,
        documents: List[DocumentReference],
        progress_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        *,
        checklist_spec: Optional[Dict[str, Any]] = None,
        focus_context: Optional[str] = None,
        run_title: Optional[str] = None,
    ) -> ClusterExtractionResult:
        ...


class ClusterChecklistExtractionEngine:
    name = "cluster"

    async def run(
        self,
        backend_run_id: str,
        corpus_id: str,
        documents: List[DocumentReference],
        progress_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        *,
        checklist_spec: Optional[Dict[str, Any]] = None,
        focus_context: Optional[str] = None,
        run_title: Optional[str] = None,
    ) -> ClusterExtractionResult:
        return await run_cluster_extraction(
            backend_run_id,
            corpus_id,
            documents,
            progress_callback=progress_callback,
            checklist_spec=checklist_spec,
            focus_context=focus_context,
            run_title=run_title,
        )


class SpoofChecklistExtractionEngine:
    name = "spoof"

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self._settings = settings or get_settings()

    async def run(
        self,
        backend_run_id: str,
        corpus_id: str,
        documents: List[DocumentReference],
        progress_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        *,
        checklist_spec: Optional[Dict[str, Any]] = None,
        focus_context: Optional[str] = None,
        run_title: Optional[str] = None,
    ) -> ClusterExtractionResult:
        fixture_dir = resolve_spoof_fixture_dir(self._settings.cluster_spoof_extraction_fixture_dir)
        request_payload = load_spoof_request_payload(fixture_dir)
        validate_fixture_corpus(corpus_id, request_payload, label="Spoof extraction fixture")
        validate_fixture_document_ids(
            [document.id for document in documents],
            request_payload,
            label="Spoof extraction fixture",
        )

        events = load_spoof_events(fixture_dir / "events.ndjson")
        terminal_event = await replay_spoof_events(
            events,
            progress_callback=progress_callback,
            delay_seconds=max(0.0, float(self._settings.cluster_spoof_event_delay_seconds)),
        )
        require_completed_terminal_event(terminal_event, label="Spoof extraction fixture")

        checklist_payload = load_spoof_json(fixture_dir / "checklist.json")
        document_map_payload = load_spoof_json(fixture_dir / "document_map.json")
        if not isinstance(checklist_payload, dict):
            raise RuntimeError(f"Spoof extraction fixture checklist.json must be a JSON object: {fixture_dir}")

        runner = ClusterChecklistRunner()
        collection = runner._collection_from_checklist_payload(  # pylint: disable=protected-access
            checklist_payload=checklist_payload,
            document_map_payload=document_map_payload,
            documents=documents,
        )
        terminal_data = terminal_event.get("data")
        payload = dict(terminal_data) if isinstance(terminal_data, dict) else {}
        run_id = str(payload.get("run_id") or "").strip() or None
        job_id = str(payload.get("job_id") or "").strip() or None
        return ClusterExtractionResult(
            collection=collection,
            run_id=run_id,
            job_id=job_id,
            output_dir=str(payload.get("output_dir") or "").strip() or None,
            manifest_path=str(payload.get("manifest_path") or "").strip() or None,
            result_payload_path=str((fixture_dir / "result_payload.json").resolve()),
            checklist_ndjson_path=str((fixture_dir / "checklist.json").resolve()),
        )


_CLUSTER_ENGINE = ClusterChecklistExtractionEngine()


def get_checklist_extraction_engine() -> ChecklistExtractionEngine:
    settings = get_settings()
    if settings.cluster_run_mode == "spoof":
        return SpoofChecklistExtractionEngine(settings)
    return _CLUSTER_ENGINE
