from __future__ import annotations

from typing import List, Protocol

from app.core.config import get_settings
from app.schemas.checklists import EvidenceCollection
from app.schemas.documents import DocumentReference
from app.services.cluster_extraction import run_cluster_extraction


class ChecklistExtractionEngine(Protocol):
    name: str

    async def run(self, case_id: str, documents: List[DocumentReference]) -> EvidenceCollection:
        ...


class LocalChecklistExtractionEngine:
    name = "local"

    async def run(self, case_id: str, documents: List[DocumentReference]) -> EvidenceCollection:
        del documents
        from app.services.agent.driver import run_extraction_agent

        return await run_extraction_agent(case_id)


class ClusterChecklistExtractionEngine:
    name = "cluster"

    async def run(self, case_id: str, documents: List[DocumentReference]) -> EvidenceCollection:
        return await run_cluster_extraction(case_id, documents)


_LOCAL_ENGINE = LocalChecklistExtractionEngine()
_CLUSTER_ENGINE = ClusterChecklistExtractionEngine()


def get_checklist_extraction_engine() -> ChecklistExtractionEngine:
    settings = get_settings()
    if settings.checklist_extraction_mode == "cluster":
        return _CLUSTER_ENGINE
    return _LOCAL_ENGINE
