# Interface Agents

`interface_agents/` contains the remote execution code that the backend stages to the SLURM head node for extraction and summary jobs.

This directory is not part of the browser app and not part of the FastAPI service. It is the staged worker/controller code snapshot that actually runs on the cluster.

## What This Directory Owns
- The checklist extraction controller and worker runtime.
- The summary generation controller and worker runtime.
- The canonical JSON request contract read from stdin by both controllers.
- The SLURM submission scripts used by the controllers.
- The run-local artifact layout under each controller's `runs/<run_id>/` directory.
- The shared Python dependency set required by both agents.

## Design Principles
- One staged snapshot per backend run: the backend rsyncs this whole directory into a fresh remote stage directory for every backend run.
- Controller-worker split: controllers validate requests, preprocess inputs, submit SLURM jobs, stream NDJSON events, and ingest worker artifacts.
- Native runtime is the live path: the current backend-led flow uses the GPT-OSS native tool-calling workers.
- Canonical contract only: both controllers require the modern `input.corpus_id` and `input.documents[]` envelope.
- Artifact-first integration: the backend consumes controller artifacts such as `result_payload.json`, `checklist.json`, `checklist.ndjson`, and `summary.json`.

## Directory Layout
```text
interface_agents/
├── requirements.txt
├── HANDOFF_to_backend.md
├── checklist_agent/
│   ├── controller/
│   ├── native/
│   ├── agent/
│   ├── state/
│   ├── config/
│   ├── run_agent.py
│   ├── run_agent.sbatch
│   └── run_agent_native.sbatch
└── summary_agent/
    ├── controller/
    ├── native/
    ├── runtime/
    ├── run_summary_agent_native.py
    └── run_summary_agent_native.sbatch
```

## Subsystems
### Shared Dependency Root
Shared Python dependencies live in:
- `interface_agents/requirements.txt`

This is the environment spec the remote cluster Python environment should install for backend-led staged runs.

### Checklist Agent
Checklist extraction lives under:
- `interface_agents/checklist_agent/`

The live backend-led path is:
- controller:
  - `interface_agents/checklist_agent/controller/run_controller_native.py`
  - `interface_agents/checklist_agent/controller/run_controller.py`
- native worker:
  - `interface_agents/checklist_agent/native/run_agent_native.py`
  - `interface_agents/checklist_agent/native/driver_native.py`
  - `interface_agents/checklist_agent/run_agent_native.sbatch`

Responsibilities:
- validate the extraction request contract
- preprocess raw documents into the local corpus layout
- generate run-local checklist YAML from inline backend checklist configuration
- submit one or more SLURM checklist jobs
- stream NDJSON progress events
- convert final evidence spans into controller-level offset artifacts

Checklist controller artifacts land under:
- `interface_agents/checklist_agent/controller/runs/<run_id>/`

The checklist subtree also still contains an older direct-run stack:
- `run_agent.py`
- `run_agent.sbatch`
- `agent/driver.py`
- `agent/orchestrator.py`
- `agent/llm_client.py`
- `config/checklist_configs/...`

That older stack is not the source of truth for backend-led staged runs. It is intentionally retained for direct/manual runs, debugging, and future runtime expansion work.

Important note:
- this older direct-run path should be treated as reserved capability, not as accidental dead code
- it is the natural place to re-expand custom scaffolding behavior later if a future model family requires it
- it is also useful when you want to debug worker behavior without going through the full backend-to-controller-to-SLURM flow

### Summary Agent
Summary generation lives under:
- `interface_agents/summary_agent/`

The live backend-led path is:
- controller:
  - `interface_agents/summary_agent/controller/run_controller.py`
- native worker:
  - `interface_agents/summary_agent/run_summary_agent_native.py`
  - `interface_agents/summary_agent/native/driver_native.py`
  - `interface_agents/summary_agent/run_summary_agent_native.sbatch`
- runtime state/tools:
  - `interface_agents/summary_agent/runtime/...`

Responsibilities:
- validate the summary request contract
- reuse checklist-agent preprocessing to reconstruct the processed corpus
- convert evidence offsets into sentence spans for prompt/runtime use
- submit one SLURM summary job
- stream NDJSON progress events
- emit final summary artifacts

Summary controller artifacts land under:
- `interface_agents/summary_agent/controller/runs/<run_id>/`

## Canonical Controller Contract
Both controllers read one JSON object from stdin.

Required shared fields:
- `input`
- `input.corpus_id`
- `input.documents[]`

Each `input.documents[]` entry must include:
- `document_id`
- `title`
- `text`

Optional per-document fields:
- `doc_type`
- `date`

Checklist extraction additionally requires:
- `checklist_strategy`
- `checklist_spec`

Summary generation additionally requires:
- `checklist`
- `checklist_definitions`

There are no compatibility aliases for the old envelope names.

## Event Contract
Both controllers emit NDJSON events to stdout.

Important characteristics:
- every event includes `event_type`, `request_id`, `seq`, `timestamp`, and `data`
- the backend treats stdout as the progress/event channel
- terminal events are `completed` or `failed`
- controller runs also mirror the same NDJSON stream into `events.ndjson`

## Runtime Configuration
Each staged run uses controller-local `.env` files generated by the backend.

Important behavior:
- checklist agent reads `.env` from `interface_agents/checklist_agent/.env`
- summary agent reads `.env` from `interface_agents/summary_agent/.env`
- environment variables override those files
- path values are consumed literally, so staged `.env` entries must contain concrete absolute paths

The most important staged settings are:
- staged base directory
- remote Python interpreter path
- Hugging Face cache paths
- SLURM binary directory
- sbatch script path overrides

## Artifact Model
Checklist controller outputs:
- `result_payload.json`
- `checklist.json`
- `checklist.ndjson`
- `document_map.json`
- `manifest.json`
- `events.ndjson`

Summary controller outputs:
- `result_payload.json`
- `summary.json`
- `document_map.json`
- `manifest.json`
- `events.ndjson`

For backend ingestion:
- checklist extraction should be read from controller outputs, not raw worker intermediates
- final summary text should be read from `summary.json` field `summary`

## Backend Integration
The backend stages this directory into a fresh remote run directory and then launches:
- checklist extraction from the staged checklist controller
- summary generation from the staged summary controller

Both stages for one backend run use the same staged `interface_agents/` snapshot. That means extraction and summary for one run are tied to one exact code snapshot on the remote cluster.

The backend/operator handoff for this contract is:
- `interface_agents/HANDOFF_to_backend.md`

## Key Files And Why They Matter
| Path | Responsibility |
|------|----------------|
| `requirements.txt` | Shared agent dependency set |
| `HANDOFF_to_backend.md` | Top-level backend integration contract |
| `checklist_agent/controller/run_controller_native.py` | Live checklist controller entrypoint used by the backend |
| `checklist_agent/controller/run_controller.py` | Core checklist controller logic and event emission |
| `checklist_agent/native/driver_native.py` | Live GPT-OSS checklist worker runtime |
| `checklist_agent/native/run_agent_native.py` | Checklist native CLI entrypoint |
| `checklist_agent/run_agent_native.sbatch` | Checklist SLURM submission wrapper used by the controller |
| `checklist_agent/data_processing.py` | Corpus preprocessing used by checklist and reused by summary |
| `summary_agent/controller/run_controller.py` | Live summary controller entrypoint used by the backend |
| `summary_agent/native/driver_native.py` | Live GPT-OSS summary worker runtime |
| `summary_agent/run_summary_agent_native.py` | Summary native CLI entrypoint |
| `summary_agent/run_summary_agent_native.sbatch` | Summary SLURM submission wrapper used by the controller |
| `summary_agent/runtime/summary_state.py` | Summary state store used by runtime tools |
| `summary_agent/runtime/tools/*` | Summary editing tools available to the native worker |

## Intentional Retained Legacy Surface
Some code in this directory is old but intentionally preserved.

### Direct-Run Checklist Stack
The older checklist direct-run path is still present by design:
- `checklist_agent/run_agent.py`
- `checklist_agent/run_agent.sbatch`
- `checklist_agent/agent/driver.py`
- `checklist_agent/agent/orchestrator.py`
- `checklist_agent/agent/llm_client.py`

Why it is still here:
- it is useful for low-friction debugging when you want to inspect worker behavior directly
- it provides a simpler path for isolated experiments outside the staged backend workflow
- it is the most likely place to extend custom model-specific scaffolding later

### Custom Scaffolding And Model-Specific Prompting
The checklist side still includes older model-specific prompt/config scaffolding such as:
- `checklist_agent/config/prompts_gpt_oss.yaml`
- `checklist_agent/config/prompts_qwen.yaml`
- `checklist_agent/config/model_config.yaml`
- `checklist_agent/config/checklist_configs/...`

Why it is still here:
- some model families may require custom scaffolding or prompt assembly that differs from the current native GPT-OSS path
- Qwen-specific support in particular is a plausible future re-expansion target
- the backend-led staged workflow does not currently use these files as its source of truth, but they remain useful operator/debugging assets

### What Is Live vs. What Is Reserved
Live backend-led path:
- checklist controller + native worker
- summary controller + native worker
- canonical stdin JSON contract

Reserved but not currently primary:
- direct-run checklist path
- model-specific prompt/config scaffolding outside the backend-led generated checklist flow

These reserved paths should not be mistaken for accidental loose ends. They are retained on purpose so the repository can support future debugging and model-specific runtime work without having to recreate that scaffolding from scratch.
