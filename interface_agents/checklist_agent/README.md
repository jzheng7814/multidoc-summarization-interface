# Checklist Agent Runtime

`interface_agents/checklist_agent` is the staged extraction runtime used by backend-led checklist runs.

The backend sends inline checklist configuration, the controller preprocesses the document corpus, and the controller launches one or more SLURM-backed checklist worker jobs.

## What This Module Produces
For each controller run, the checklist controller writes:
- `result_payload.json`
- `checklist.json`
- `checklist.ndjson`
- `document_map.json`
- `manifest.json`
- `events.ndjson`

Artifacts live under:
- `interface_agents/checklist_agent/controller/runs/<run_id>/`

## Runtime Layout
```text
interface_agents/checklist_agent/
├── run_agent.py
├── run_agent.sbatch
├── run_agent_native.sbatch
├── native/
│   ├── run_agent_native.py
│   ├── driver_native.py
│   ├── gpt_oss_native_client.py
│   ├── prompts_gpt_oss_native.yaml
│   ├── stop_tool.py
│   └── update_derived_state_tool.py
├── agent/
├── controller/
│   ├── run_controller.py
│   ├── run_controller_native.py
│   ├── requests/
│   └── runs/
├── state/
└── config/
```

## Controller Entrypoints
Standard controller:
```bash
cat /path/to/request.json | \
/coc/pskynet6/jzheng390/miniconda3/envs/gavel-dev/bin/python \
interface_agents/checklist_agent/controller/run_controller.py \
--mode slurm_extract_strategy --poll-seconds 2 --max-wait-seconds 21600
```

Native controller:
```bash
cat /path/to/request.json | \
/coc/pskynet6/jzheng390/miniconda3/envs/gavel-dev/bin/python \
interface_agents/checklist_agent/controller/run_controller_native.py \
--mode slurm_extract_strategy --poll-seconds 2 --max-wait-seconds 21600
```

`run_controller_native.py` is a wrapper over `run_controller.py`. The request contract and event schema are identical.

## Runtime Configuration
Path settings are loaded from `.env` inside the staged `interface_agents/checklist_agent/` directory. In the normal backend workflow that file is generated automatically for each staged run. Environment variables still override `.env`.

## Canonical Controller Request Contract
The controller reads one JSON object from stdin.

Required top-level fields:
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

### `checklist_strategy = "all"`
Required:
- `checklist_spec.user_instruction`
- `checklist_spec.constraints`
- `checklist_spec.checklist_items[]` with `key` and `description`
- top-level `max_steps`
- top-level `reasoning_effort`

### `checklist_strategy = "individual"`
Required:
- `checklist_spec.checklist_items[]`
- each item must include:
  - `key`
  - `description`
  - `user_instruction`
  - `constraints`
  - `max_steps`
  - `reasoning_effort`

Top-level `max_steps` and `reasoning_effort` are rejected in `individual` mode.

Optional top-level fields:
- `request_id`
- `model`
- `focus_context`
- `resume`
- `debug`
- `slurm.partition`
- `slurm.qos`

There are no compatibility aliases. The controller accepts only the canonical `input` envelope.

## Checklist Config Source of Truth
For backend-led controller runs:
1. the backend sends inline `checklist_spec`
2. the controller generates run-local YAML files under `controller/runs/<run_id>/generated_checklists/`
3. the controller launches each worker job against those generated files

The legacy YAML files under `config/checklist_configs/` are still useful for direct CLI runs, but they are not the source of truth for backend-led staged runs.

## Evidence Schema
Per-item agent outputs use sentence-span evidence. The controller-level final output converts those spans into character offsets:
- `source_document_id`
- `start_offset` (inclusive, 0-based)
- `end_offset` (exclusive, 0-based)

Backend ingestion should always use controller outputs such as `checklist.json` and `result_payload.json`, not raw worker intermediates.

## Direct Runs
Direct runs still support `--checklist-config` for local experiments:
```bash
python run_agent.py data/<dataset>/<corpus_id> \
  --checklist-config config/checklist_configs/individual/08_judge_name.yaml
```

Those direct runs are separate from the backend-led staged contract.

## Related Files
- checklist native prompt: `interface_agents/checklist_agent/native/prompts_gpt_oss_native.yaml`
- direct-run checklist config notes: `interface_agents/checklist_agent/config/checklist_configs/README.md`
