# Summary Agent (Checklist-Grounded Native Runtime)

`summary_agent` is the agentic summary-generation counterpart to checklist extraction.

It mirrors the native GPT-OSS workflow and controller pattern used in
`interface_agents/checklist_agent`, but writes a narrative case summary
instead of checklist fields.

Runtime path settings are loaded from `.env` inside the staged
`interface_agents/summary_agent/` directory (see `.env.example`). In the normal backend
workflow this file is generated automatically for each staged run.

## What It Produces

Controller runs write artifacts under:
- `interface_agents/summary_agent/controller/runs/<run_id>/`

Key files:
- `result_payload.json` (authoritative run payload)
- `summary.json` (final summary string + summary stats)
- `manifest.json` (artifact index)
- `document_map.json`
- `events.ndjson` (controller event stream mirror)

Agent execution artifacts live under:
- `interface_agents/summary_agent/controller/runs/<run_id>/agent_output/<model>/<case_id>/summary_agent/`

Including:
- `summary_state.json`
- `ledger.jsonl`
- `stats.json`
- `run_<id>.json`

## Runtime Layout

```text
summary_agent/
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
│       ├── append_summary.py
│       ├── update_summary.py
│       ├── delete_summary.py
│       └── get_summary_state.py
└── controller/
    ├── run_controller.py
    ├── HANDOFF_to_backend.md
    ├── requests/
    └── runs/
```

## Request Contract (Controller)

Controller mode accepts one JSON object on stdin.

Required:
- one case in `case` or `input_case` or single-entry `cases`
- `checklist` object (offset-based evidence map)
- `checklist_definitions` object (`{item_name: definition}`)

Optional:
- `request_id` (default: controller run_id)
- `model` (default: `unsloth/gpt-oss-20b-BF16`)
- `max_steps` (default: `200`)
- `reasoning_effort` (`low|medium|high`, default: `medium`)
- `summary_constraints` (list of strings)
- `focus_context` (optional non-empty string injected into per-turn prompt context)
- `k_recent_tool_outputs` (default: `5`)
- `resume` (bool)
- `debug` (bool)
- `prompt_config` (path string)
- `python_bin` (override preprocessing python)
- `slurm.partition`, `slurm.qos` (defaults `nlprx-lab`, `short`)

Evidence input contract:
- Checklist evidence offsets are expected as zero-based half-open ranges:
  - `start_offset` inclusive
  - `end_offset` exclusive

The controller preprocesses the case corpus and converts offsets to sentence spans before launch.

## Run Through Controller (Backend Pattern)

```bash
cat /path/to/request.json | \
/coc/pskynet6/jzheng390/miniconda3/envs/gavel-dev/bin/python \
interface_agents/summary_agent/controller/run_controller.py \
--mode slurm_summarize_agent --poll-seconds 2 --max-wait-seconds 21600
```

## Run Native Worker Directly

```bash
/coc/pskynet6/jzheng390/miniconda3/envs/gavel-dev/bin/python \
interface_agents/summary_agent/run_summary_agent_native.py \
/path/to/corpus_dir \
--request-json /path/to/agent_request.json \
--model unsloth/gpt-oss-20b-BF16
```

## Backend Handoff

- `interface_agents/summary_agent/controller/HANDOFF_to_backend.md`
