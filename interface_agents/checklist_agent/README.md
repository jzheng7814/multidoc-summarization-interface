# Interface Agent (Checklist Extraction Runtime)

`interface_agents/checklist_agent` is the isolated document-level checklist extraction runtime used in GAVEL.

It supports two execution scaffolds:
- **Custom scaffold** (`agent/`): explicit controller loop + tool JSON parsing.
- **Native scaffold** (`native/`): GPT-OSS Harmony native tool-calling.

As of March 2026, the production-facing run contract is implemented in
`controller/run_controller.py` (and reused by `controller/run_controller_native.py`).

## What This Module Produces

For each run/case, the controller writes:
- `result_payload.json` (authoritative run metadata + checklist + per-item jobs)
- `checklist.json` (final offset-based checklist)
- `checklist.ndjson` (stream-friendly checklist rows)
- `document_map.json` (doc ID mapping)
- `manifest.json` (artifact index + stats)

Artifacts are stored under:
- `controller/runs/<run_id>/`

## Runtime Layout

```text
interface_agents/checklist_agent/
├── run_agent.py                      # Custom scaffold entrypoint
├── run_agent.sbatch                  # SLURM launcher for custom scaffold
├── run_agent_native.sbatch           # SLURM launcher for native scaffold
├── native/
│   ├── run_agent_native.py           # Native scaffold entrypoint
│   ├── driver_native.py              # Native loop + tool wiring
│   ├── gpt_oss_native_client.py      # Harmony client wrapper
│   ├── prompts_gpt_oss_native.yaml   # Native developer prompt
│   ├── stop_tool.py
│   └── update_derived_state_tool.py
├── agent/
│   ├── driver.py                     # Custom loop
│   ├── orchestrator.py               # Custom action planner
│   ├── snapshot_builder.py
│   ├── snapshot_formatter.py
│   └── tools/
├── controller/
│   ├── run_controller.py             # Standard controller
│   ├── run_controller_native.py      # Native wrapper (same contract, native sbatch)
│   └── requests/ and runs/           # Runtime inputs/logs/artifacts
├── state/
│   ├── store.py
│   └── schemas.py
└── config/
    ├── model_config.yaml
    ├── prompts_gpt_oss.yaml
    ├── prompts_qwen.yaml
    └── checklist_configs/
```

## Controller Modes

Path settings for controller and sbatch are loaded from `.env` inside the staged
`interface_agents/checklist_agent/` directory (see `.env.example`). In the normal backend
workflow this file is generated automatically for each staged run. Environment variables
still override `.env`.

### 1) Standard controller

```bash
cat /path/to/request.json | \
/coc/pskynet6/jzheng390/miniconda3/envs/gavel-dev/bin/python \
interface_agents/checklist_agent/controller/run_controller.py \
--mode slurm_extract_strategy --poll-seconds 2 --max-wait-seconds 21600
```

Uses `run_agent.sbatch`.

### 2) Native controller

```bash
cat /path/to/request.json | \
/coc/pskynet6/jzheng390/miniconda3/envs/gavel-dev/bin/python \
interface_agents/checklist_agent/controller/run_controller_native.py \
--mode slurm_extract_strategy --poll-seconds 2 --max-wait-seconds 21600
```

Uses `run_agent_native.sbatch`.

`run_controller_native.py` is a wrapper over `run_controller.py`; contract + event schema are the same.

## Request Contract (Current)

The request is JSON on stdin.

### Required high-level fields
- one case in `case` or `input_case` or single-entry `cases`
- `checklist_strategy`: `"all"` or `"individual"`
- `checklist_spec`

### `checklist_strategy = "all"`
- `checklist_spec.user_instruction` (non-empty string)
- `checklist_spec.constraints` (array of strings; empty allowed, null disallowed)
- `checklist_spec.checklist_items` with items:
  - `key` (non-empty string)
  - `description` (non-empty string)
- runtime tuning at top-level:
  - `max_steps` (>=1)
  - `reasoning_effort` (`low|medium|high`)

### `checklist_strategy = "individual"`
- `checklist_spec.checklist_items` with items:
  - `key` (non-empty string)
  - `description` (non-empty string)
  - `user_instruction` (non-empty string)
  - `constraints` (array; empty allowed)
  - `max_steps` (>=1)
  - `reasoning_effort` (`low|medium|high`)
- top-level `max_steps` and `reasoning_effort` are rejected for this mode.

### Optional fields
- `model` (default `unsloth/gpt-oss-20b-BF16`)
- `focus_context` (optional non-empty string injected per turn)
- `resume` (bool)
- `debug` (bool)
- `max_concurrent` (currently only `1` supported in strategy mode)

## Checklist Config Source of Truth

For **controller-driven runs**, checklist config paths are no longer accepted in request payloads.

The controller now:
1. accepts **inline** `checklist_spec`
2. generates run-local YAML files under `controller/runs/<run_id>/generated_checklists/`
3. launches each SLURM job against those generated files

Path-based checklist configs are still usable for direct local CLI runs (`run_agent.py`, `run_agent_native.py`) via `--checklist-config`.

## Native-Specific Notes

Native runtime (`native/driver_native.py`) includes:
- GPT-OSS Harmony tool schema injection
- explicit `stop` tool (two-stage stop review)
- optional run-level `focus_context` prompt injection
- `update_derived_state` tool for compact working memory
- compact memory strategy: full tool outputs for most recent K turns (`--k-recent-tool-outputs`, default `5`), summarized older turns

## Evidence and Final Schema

Per-item agent outputs store sentence-span evidence (`source_document_id`, `start_sentence`, `end_sentence`).

Controller-level final output converts this to **character offsets**:
- `source_document_id`
- `start_offset` (inclusive, 0-based)
- `end_offset` (exclusive, 0-based)

Backend should ingest controller-level outputs (`result_payload.json`, `checklist.json`, etc.), not raw per-item intermediate structures.

## Recovery and Reruns

- For targeted reruns, issue a single-item request through `run_controller.py` or `run_controller_native.py`.
- Native recoveries should prefer `run_controller_native.py` for parity with production path.

## Development Notes

### Install

```bash
pip install -r ../requirements.txt
```

### Quick checks

```bash
/coc/pskynet6/jzheng390/miniconda3/envs/gavel-dev/bin/python -m py_compile \
interface_agents/checklist_agent/native/driver_native.py
```

## Related Docs

- Checklist config notes:
  - `interface_agents/checklist_agent/config/checklist_configs/README.md`
