# Checklist Controller Handoff Contract

Date: 2026-04-05

## Entrypoints
- `interface_agents/checklist_agent/controller/run_controller.py`
- `interface_agents/checklist_agent/controller/run_controller_native.py`
- mode: `slurm_extract_strategy`

## Canonical Request Contract
The checklist controller accepts one JSON object on stdin.

Required fields:
- `input`
- `checklist_strategy`
- `checklist_spec`

Required `input` fields:
- `corpus_id`
- `documents[]`

Each `documents[]` entry must include:
- `document_id`
- `title`
- `text`

Optional document fields:
- `doc_type`
- `date`

`checklist_strategy = "all"` requires:
- `checklist_spec.user_instruction`
- `checklist_spec.constraints`
- `checklist_spec.checklist_items[]` with `key` and `description`
- top-level `max_steps`
- top-level `reasoning_effort`

`checklist_strategy = "individual"` requires:
- `checklist_spec.checklist_items[]`
- each item with `key`, `description`, `user_instruction`, `constraints`, `max_steps`, `reasoning_effort`

Optional fields:
- `request_id`
- `model`
- `focus_context`
- `resume`
- `debug`
- `slurm.partition`
- `slurm.qos`

There are no compatibility aliases.

## Controller Outputs
Controller artifacts:
- `events.ndjson`
- `request.json`
- `result_payload.json`
- `checklist.json`
- `checklist.ndjson`
- `document_map.json`
- `manifest.json`

Controller artifacts live under:
- `interface_agents/checklist_agent/controller/runs/<run_id>/`
