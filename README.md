# Multi-Document Summarization Interface

Multi-Document Summarization Interface is a run-centric application for ingesting a related document corpus, extracting structured findings with remote agents, reviewing those findings with cited evidence, and generating an editable grounded summary. The application runtime is generic. Domain behavior comes from editable checklist specs, focus-context templates, and prompt files.

## Repository Layout
- `frontend/` – React + Vite client for run creation, extraction review, and summary editing.
- `backend/` – FastAPI service, run store, background orchestration, staged remote execution, schemas, and API routes.
- `backend/app/resources/` – Default extraction checklist spec and default extraction/summary focus templates.
- `interface_agents/` – Remote checklist and summary runtimes that the backend stages to the SLURM head node for each backend run.
- `docs/` – Operator notes and migration/porting documentation.
- `tools/`, `scratch/` – Local experiments and scratch assets outside the normal application runtime.

## Setup
### Prerequisites
| Component | Requirement |
|-----------|-------------|
| Backend | Python 3.11+, `pip`, virtualenv |
| Frontend | Node.js 18+ and `npm` |
| Local operator tools | `ssh` and `rsync` |
| Remote execution | Access to a SLURM head node plus a writable scratch or flash allocation |
| Remote runtime | A persistent Python environment and model/cache storage on the cluster |

### 1) Local backend setup
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### 2) Local frontend setup
```bash
cd frontend
npm install
cp .env.example .env
```

### 3) One-time SLURM head node setup
Remote execution uses one persistent environment and one fresh staged code snapshot per backend run.

Remote layout:
```text
<remote-flash>/
├── miniconda3/
├── hf_cache/
└── interface_agent_runs/
    └── <backend-run-id>/
        ├── interface_agents/
        └── stage_manifest.json
```

Create the persistent directories:
```bash
export REMOTE_HOST=sky1
export REMOTE_FLASH=/coc/pskynet6/$USER/flash
export REMOTE_ENV_NAME=gavel-dev

ssh "$REMOTE_HOST" "mkdir -p \"$REMOTE_FLASH/interface_agent_runs\" \"$REMOTE_FLASH/hf_cache\""
```

Install Miniconda under the flash root. If you already have a working Miniconda tree elsewhere, make the flash path point at it:
```bash
ssh "$REMOTE_HOST" "ln -sfn /coc/pskynet6/$USER/miniconda3 \"$REMOTE_FLASH/miniconda3\""
```

Create the persistent runtime environment:
```bash
ssh "$REMOTE_HOST" "\"$REMOTE_FLASH/miniconda3/bin/conda\" create -y -n \"$REMOTE_ENV_NAME\" python=3.10"
```

Bootstrap the shared agent dependencies once:
```bash
rsync -az \
  --exclude='.env' \
  --exclude='agent_logs/' \
  --exclude='data/' \
  --exclude='controller/runs/' \
  --exclude='controller/requests/' \
  --exclude='__pycache__/' \
  ./interface_agents/ \
  "$REMOTE_HOST:$REMOTE_FLASH/bootstrap/interface_agents/"

ssh "$REMOTE_HOST" "\"$REMOTE_FLASH/miniconda3/envs/$REMOTE_ENV_NAME/bin/python\" -m pip install --upgrade pip && \
\"$REMOTE_FLASH/miniconda3/envs/$REMOTE_ENV_NAME/bin/python\" -m pip install -r \"$REMOTE_FLASH/bootstrap/interface_agents/requirements.txt\""
```

Record these three paths. The backend needs all of them:
- remote stage root: `<remote-flash>/interface_agent_runs`
- remote python: `<remote-flash>/miniconda3/envs/<env-name>/bin/python`
- remote HF cache: `<remote-flash>/hf_cache`

### 4) Configure backend remote wiring
Edit `backend/.env` to match the one-time remote setup.

| Variable | Purpose |
|----------|---------|
| `MULTI_DOCUMENT_CLUSTER_RUN_MODE` | `remote` for real cluster jobs, `spoof` for fixture-backed replay |
| `MULTI_DOCUMENT_CLUSTER_SSH_HOST` | SSH host for the SLURM head node |
| `MULTI_DOCUMENT_CLUSTER_REMOTE_STAGE_ROOT` | Root directory where the backend creates per-run staged snapshots |
| `MULTI_DOCUMENT_CLUSTER_REMOTE_PYTHON_PATH` | Absolute path to the persistent remote Python interpreter |
| `MULTI_DOCUMENT_CLUSTER_REMOTE_HF_CACHE_DIR` | Shared Hugging Face cache directory on the head node |
| `MULTI_DOCUMENT_CLUSTER_REMOTE_SLURM_BIN_DIR` | Directory that contains `sbatch`, `squeue`, and `sacct` |
| `MULTI_DOCUMENT_CLUSTER_REMOTE_CONTROLLER_SCRIPT` | Checklist controller entrypoint relative to the staged run directory |
| `MULTI_DOCUMENT_CLUSTER_SUMMARY_REMOTE_CONTROLLER_SCRIPT` | Summary controller entrypoint relative to the staged run directory |
| `MULTI_DOCUMENT_CLUSTER_SLURM_PARTITION` | SLURM partition for checklist jobs |
| `MULTI_DOCUMENT_CLUSTER_SLURM_QOS` | SLURM QoS for checklist jobs |
| `MULTI_DOCUMENT_CLUSTER_SUMMARY_SLURM_PARTITION` | SLURM partition for summary jobs |
| `MULTI_DOCUMENT_CLUSTER_SUMMARY_SLURM_QOS` | SLURM QoS for summary jobs |

### 5) How remote execution works
For every backend run:
1. The backend creates `<remote-stage-root>/<backend-run-id>/` on the head node.
2. The backend rsyncs the local `interface_agents/` tree into that directory.
3. The backend writes stage-local `.env` files into the staged checklist and summary directories.
4. Checklist extraction launches from that staged snapshot.
5. Summary generation launches from the same staged snapshot after extraction completes.
6. All controller artifacts remain in that stage directory until you delete them manually.

The backend does not depend on a long-lived remote checkout of this repository.

## Running the App
### Start the backend
```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Start the frontend
```bash
cd frontend
npm run dev
```

The frontend defaults to `http://localhost:5173`, and the backend defaults to `http://localhost:8000`.

## Development Modes
### Spoof mode
Spoof mode replays recorded extraction and summary fixtures without dispatching real cluster jobs.

```bash
MULTI_DOCUMENT_CLUSTER_RUN_MODE=spoof
```

### Remote mode
Remote mode stages `interface_agents/` to the head node and dispatches real extraction and summary jobs through the agent controllers.

```bash
MULTI_DOCUMENT_CLUSTER_RUN_MODE=remote
```

Remote mode requires:
- working `ssh` and `rsync` locally
- a reachable SLURM head node
- a persistent remote Python environment with `interface_agents/requirements.txt` installed
- valid remote stage, cache, and SLURM paths in `backend/.env`

## Run Customization
Every new run starts with backend-provided defaults for both extraction and summary. The setup page lets you edit those values before launching extraction.

### Extraction configuration
The extraction configuration consists of:
- `focus_context`
- `checklist_spec.checklist_items[]`

Each checklist item exposes:
- `key`
- `description`
- `user_instruction`
- `constraints`
- `max_steps`
- `reasoning_effort`

The frontend import/export feature uses the raw controller-facing extraction config shape. It intentionally excludes document text.

### Summary configuration
The summary configuration consists of:
- `focus_context`
- `max_steps`
- `reasoning_effort`

The frontend import/export feature uses the raw summary config shape. It intentionally excludes document text and extracted checklist content.

## Default Resource Files
New runs are initialized from these backend resource files:
- extraction checklist spec: `backend/app/resources/checklists/remote_checklist_spec.individual.json`
- extraction focus template: `backend/app/resources/checklists/focus_context.template.txt`
- summary focus template: `backend/app/resources/summary/focus_context.template.txt`

These files are the source of truth for backend-provided defaults.

## Template Placeholders
Both default focus templates support runtime placeholder substitution.

Supported placeholder:
- `#RUN_TITLE`

The backend resolves placeholders before sending requests to the remote controllers. Missing placeholder values fail fast.

## Prompt and Runtime Customization
Prompt files that matter for backend-led runs:
- checklist native prompt: `interface_agents/checklist_agent/native/prompts_gpt_oss_native.yaml`
- summary native prompt: `interface_agents/summary_agent/native/prompts_gpt_oss_summary_native.yaml`

The summary runtime also supports a prompt override path through `MULTI_DOCUMENT_CLUSTER_SUMMARY_PROMPT_CONFIG` or the per-run `prompt_config` field.

For backend-led checklist runs, the legacy YAML files under `interface_agents/checklist_agent/config/checklist_configs/` are not the runtime source of truth. The backend sends inline `checklist_spec`, and the controller generates run-local YAML files from that payload.

## Domain Adaptation
To adapt the application to a new domain:
1. Replace the default extraction checklist spec in `backend/app/resources/checklists/remote_checklist_spec.individual.json`.
2. Replace the extraction and summary focus templates in `backend/app/resources/checklists/focus_context.template.txt` and `backend/app/resources/summary/focus_context.template.txt`.
3. Update the prompt YAML files if the new domain needs different agent instructions.
4. Optionally override any of those values per run in the frontend before launching extraction.

The current checked-in checklist spec is only one default domain configuration. The application runtime is not tied to that domain.

## Notes
- `interface_agent_runs/` cleanup is manual. The backend keeps run directories in place so you can inspect the exact staged snapshot and artifacts for each run.
