from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Protocol

from app.core.config import get_settings
from app.schemas.checklists import EvidenceCollection
from app.schemas.documents import DocumentReference
from app.services.cluster_extraction import run_cluster_extraction


class ChecklistExtractionEngine(Protocol):
    name: str

    async def run(
        self,
        case_id: str,
        documents: List[DocumentReference],
        progress_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> EvidenceCollection:
        ...


class LocalChecklistExtractionEngine:
    name = "local"

    async def run(
        self,
        case_id: str,
        documents: List[DocumentReference],
        progress_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> EvidenceCollection:
        del documents
        del progress_callback
        from app.services.agent.driver import run_extraction_agent

        return await run_extraction_agent(case_id)


class ClusterChecklistExtractionEngine:
    name = "cluster"

    async def run(
        self,
        case_id: str,
        documents: List[DocumentReference],
        progress_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> EvidenceCollection:
        return await run_cluster_extraction(case_id, documents, progress_callback=progress_callback)


_LOCAL_ENGINE = LocalChecklistExtractionEngine()
_CLUSTER_ENGINE = ClusterChecklistExtractionEngine()


def get_checklist_extraction_engine() -> ChecklistExtractionEngine:
    settings = get_settings()
    if settings.checklist_extraction_mode == "cluster":
        return _CLUSTER_ENGINE
    return _LOCAL_ENGINE
