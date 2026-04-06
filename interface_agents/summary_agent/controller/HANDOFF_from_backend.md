# Handoff To Remote Agent

## Purpose
Execute one manual summary-controller run using a request payload that matches the canonical backend contract.

## Canonical Payload Requirements
The request payload must include:
- `request_id`
- `input.corpus_id`
- `input.documents[]`
- `checklist`
- `checklist_definitions`

Each `input.documents[]` entry must include:
- `document_id`
- `title`
- `text`

Optional document fields:
- `doc_type`
- `date`

## Remote Invocation
```bash
cd /coc/pskynet6/jzheng390/gavel
cat /path/to/request.json | \
/coc/pskynet6/jzheng390/miniconda3/envs/gavel-dev/bin/python \
interface_agents/summary_agent/controller/run_controller.py \
--mode slurm_summarize_agent --poll-seconds 2 --max-wait-seconds 21600
```

## Expected Completion Artifacts
Required files:
- `events.ndjson`
- `request.json`
- `agent_request.json`
- `document_map.json`
- `summary.json`
- `result_payload.json`
- `manifest.json`

Canonical summary ingestion source:
- `summary.json` field `summary`
