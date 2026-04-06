# Interface Agents Backend Handoff

Date: 2026-04-05

This repository now uses split agent roots and one canonical controller contract.

## Canonical Entrypoints
Checklist extraction:
- `interface_agents/checklist_agent/controller/run_controller.py`
- `interface_agents/checklist_agent/controller/run_controller_native.py`
- mode: `slurm_extract_strategy`

Summary generation:
- `interface_agents/summary_agent/controller/run_controller.py`
- mode: `slurm_summarize_agent`

## Canonical Input Contract
Both controllers read one JSON object from stdin and require:
- `input.corpus_id`
- `input.documents[]`

Each `input.documents[]` entry must include:
- `document_id`
- `title`
- `text`

Optional document fields:
- `doc_type`
- `date`

Checklist extraction additionally requires:
- `checklist_strategy`
- `checklist_spec`

Summary generation additionally requires:
- `checklist`
- `checklist_definitions`

There are no compatibility aliases for the old single-input envelope names.

## Canonical Staged-Run Model
The backend stages `interface_agents/` into a fresh remote run directory for every backend run and launches both checklist and summary controllers from that staged snapshot.

## Acceptance Criteria
1. Checklist and summary smoke runs emit `started` and `completed`.
2. Real runs emit `request_validated`, `slurm_submitted`, and a terminal `completed` event.
3. Checklist artifacts land under `interface_agents/checklist_agent/controller/runs/<run_id>/` inside the staged snapshot.
4. Summary artifacts land under `interface_agents/summary_agent/controller/runs/<run_id>/` inside the staged snapshot.
5. Backend reads final summary text from `summary.json` field `summary`.
