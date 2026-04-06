# Summary Controller Handoff Contract

Date: 2026-04-05

## Entrypoint
- `interface_agents/summary_agent/controller/run_controller.py`
- mode: `slurm_summarize_agent`

## Canonical Request Contract
The summary controller accepts one JSON object on stdin.

Required fields:
- `input`
- `checklist`
- `checklist_definitions`

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

Optional fields:
- `request_id`
- `model`
- `max_steps`
- `reasoning_effort`
- `summary_constraints`
- `focus_context`
- `k_recent_tool_outputs`
- `resume`
- `debug`
- `prompt_config`
- `slurm.partition`
- `slurm.qos`

Checklist evidence contract:
- `start_offset` inclusive
- `end_offset` exclusive
- zero-based character offsets over raw document text

There are no compatibility aliases.

## Controller Outputs
Controller artifacts:
- `events.ndjson`
- `request.json`
- `agent_request.json`
- `document_map.json`
- `summary.json`
- `result_payload.json`
- `manifest.json`

Canonical backend ingestion source:
- `summary.json` field `summary`
