from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Sequence

from app.core.config import Settings
from app.schemas.checklists import EvidenceCollection
from app.schemas.summary import SummaryRequest
from app.services.summary_focus_context import build_summary_focus_context


def build_summary_agent_input_payload(corpus_id: str, documents: Sequence[Any]) -> Dict[str, Any]:
    return {
        "corpus_id": str(corpus_id),
        "documents": [
            {
                "document_id": str(doc.id),
                "title": doc.title,
                "doc_type": doc.type or "",
                "date": doc.date,
                "text": doc.content or "",
            }
            for doc in documents
        ],
    }


def build_summary_agent_checklist_payload(
    collection: EvidenceCollection,
    checklist_definitions: Mapping[str, str],
) -> Dict[str, Any]:
    # Canonical shape includes all definition keys with empty extracted arrays.
    checklist: Dict[str, Any] = {str(key): {"extracted": []} for key in checklist_definitions.keys()}

    for index, item in enumerate(collection.items):
        bin_id = str(item.bin_id).strip()
        if not bin_id:
            raise RuntimeError(f"Checklist item at index {index} is missing bin_id.")

        if bin_id not in checklist:
            checklist[bin_id] = {"extracted": []}

        evidence = item.evidence
        if evidence.document_id <= 0:
            raise RuntimeError(
                f"Checklist item '{bin_id}' has unsupported document_id={evidence.document_id}. "
                "Expected positive source document ids."
            )
        if evidence.start_offset is None or evidence.end_offset is None:
            raise RuntimeError(
                f"Checklist item '{bin_id}' is missing start/end offsets required for summary-agent ingestion."
            )
        if evidence.end_offset < evidence.start_offset:
            raise RuntimeError(
                f"Checklist item '{bin_id}' has invalid offsets: "
                f"start_offset={evidence.start_offset}, end_offset={evidence.end_offset}."
            )

        checklist[bin_id]["extracted"].append(
            {
                "value": item.value,
                "evidence": [
                    {
                        "source_document_id": str(evidence.document_id),
                        "start_offset": int(evidence.start_offset),
                        "end_offset": int(evidence.end_offset),
                    }
                ],
            }
        )

    return checklist


def build_summary_agent_request_payload(
    *,
    corpus_id: str,
    run_title: Optional[str],
    request_id: str,
    documents: Sequence[Any],
    checklist_collection: EvidenceCollection,
    checklist_definitions: Mapping[str, str],
    request: SummaryRequest,
    settings: Settings,
) -> Dict[str, Any]:
    focus_context = build_summary_focus_context(
        run_title=run_title,
        request_focus_context=request.focus_context,
        settings=settings,
    )

    payload: Dict[str, Any] = {
        "request_id": request_id,
        "input": build_summary_agent_input_payload(corpus_id, documents),
        "checklist_definitions": dict(checklist_definitions),
        "checklist": build_summary_agent_checklist_payload(checklist_collection, checklist_definitions),
        "model": request.model or settings.cluster_summary_model_name,
        "max_steps": request.max_steps if request.max_steps is not None else int(settings.cluster_summary_max_steps),
        "reasoning_effort": request.reasoning_effort or settings.cluster_summary_reasoning_effort,
        "k_recent_tool_outputs": (
            request.k_recent_tool_outputs
            if request.k_recent_tool_outputs is not None
            else int(settings.cluster_summary_k_recent_tool_outputs)
        ),
        "resume": bool(request.resume) if request.resume is not None else False,
        "debug": bool(request.debug) if request.debug is not None else False,
        "focus_context": focus_context,
    }

    if request.summary_constraints:
        constraints = [entry.strip() for entry in request.summary_constraints if isinstance(entry, str) and entry.strip()]
        if constraints:
            payload["summary_constraints"] = constraints

    prompt_config = request.prompt_config or settings.cluster_summary_prompt_config
    if isinstance(prompt_config, str) and prompt_config.strip():
        payload["prompt_config"] = prompt_config.strip()

    partition = (
        request.slurm.partition.strip()
        if request.slurm and isinstance(request.slurm.partition, str)
        else settings.cluster_summary_slurm_partition.strip()
    )
    qos = (
        request.slurm.qos.strip()
        if request.slurm and isinstance(request.slurm.qos, str)
        else settings.cluster_summary_slurm_qos.strip()
    )
    slurm: Dict[str, Any] = {}
    if partition:
        slurm["partition"] = partition
    if qos:
        slurm["qos"] = qos
    if slurm:
        payload["slurm"] = slurm

    return payload
