# Summary Agent Runtime

`interface_agents/summary_agent` is the staged summary-generation runtime used by backend-led summary jobs.

The backend sends the canonical corpus input, the extracted checklist with evidence offsets, and the checklist definitions. The controller preprocesses the corpus, converts offsets into sentence spans, and launches the native summary worker through SLURM.

## What This Module Produces
For each controller run, the summary controller writes:
- `result_payload.json`
- `summary.json`
- `manifest.json`
- `document_map.json`
- `events.ndjson`

Artifacts live under:
- `interface_agents/summary_agent/controller/runs/<run_id>/`

Worker execution artifacts live under:
- `interface_agents/summary_agent/controller/runs/<run_id>/agent_output/<model>/<corpus_id>/summary_agent/`

## Runtime Layout
```text
interface_agents/summary_agent/
├── run_summary_agent_native.py
├── run_summary_agent_native.sbatch
├── native/
│   ├── driver_native.py
│   ├── gpt_oss_native_client.py
│   ├── prompts_gpt_oss_summary_native.yaml
│   └── stop_tool.py
├── runtime/
│   ├── summary_state.py
│   ├── snapshot_formatter.py
│   └── tools/
└── controller/
    ├── run_controller.py
    ├── requests/
    └── runs/
```

## Controller Entrypoint
```bash
cat /path/to/request.json | \
/coc/pskynet6/jzheng390/miniconda3/envs/gavel-dev/bin/python \
interface_agents/summary_agent/controller/run_controller.py \
--mode slurm_summarize_agent --poll-seconds 2 --max-wait-seconds 21600
```

## Runtime Configuration
Path settings are loaded from `.env` inside the staged `interface_agents/summary_agent/` directory. In the normal backend workflow that file is generated automatically for each staged run. Environment variables still override `.env`.

## Canonical Controller Request Contract
The controller reads one JSON object from stdin.

Required top-level fields:
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

Optional top-level fields:
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

There are no compatibility aliases. The controller accepts only the canonical `input` envelope.

Checklist evidence contract:
- `start_offset` is inclusive
- `end_offset` is exclusive
- offsets are zero-based character offsets over raw document text

The controller converts those offsets into sentence spans before the worker runtime starts.

## Canonical Summary Text Source
Backend ingestion should read the final summary text from:
- `summary.json` field `summary`

`result_payload.json` mirrors that text, but `summary.json` is the canonical summary artifact.

## Prompt Files
The default native prompt lives at:
- `interface_agents/summary_agent/native/prompts_gpt_oss_summary_native.yaml`

A backend-led run can override that prompt path with the request field `prompt_config` or the backend env var `MULTI_DOCUMENT_CLUSTER_SUMMARY_PROMPT_CONFIG`.
