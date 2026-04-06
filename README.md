# Multi-Document Summarization Interface

Full-stack interface for reviewing a corpus of related documents, extracting structured findings with remote agents, and producing an editable grounded summary. The application is domain-agnostic. Domain-specific behavior lives in editable resource files, checklist specs, focus-context templates, and agent prompt/config files.

## Repository Layout
- `frontend/` – React + Vite client for run creation, extraction review, and summary editing.
- `backend/` – FastAPI service, run store, background job orchestration, remote staging logic, schemas, and API routes.
- `backend/app/resources/` – Editable focus templates, checklist specs, and summary resources.
- `interface_agents/` – Remote runtimes that the backend stages onto the SLURM head node for extraction and summary runs.
- `docs/` – Operator notes and porting documentation.
- `tools/`, `scratch/` – Local experiments and utilities outside the normal application runtime.

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
This application runs with a persistent remote runtime and per-run staged code snapshots.

- The persistent runtime lives under your scratch or flash allocation.
- The backend creates a fresh remote stage directory for every backend run.
- The backend rsyncs `interface_agents/` into that directory before launching extraction.
- Summary reuses the exact same staged snapshot as extraction.

The canonical remote layout is:
```text
<remote-flash>/
├── miniconda3/
├── hf_cache/
└── interface_agent_runs/
    └── <backend-run-id>/
        ├── interface_agents/
        └── stage_manifest.json
```

Use the following commands as the one-time setup contract. Replace `sky1` and `/coc/pskynet6/$USER/flash` as needed for your cluster.

```bash
export REMOTE_HOST=sky1
export REMOTE_FLASH=/coc/pskynet6/$USER/flash
export REMOTE_ENV_NAME=gavel-dev

ssh "$REMOTE_HOST" "mkdir -p \"$REMOTE_FLASH/interface_agent_runs\" \"$REMOTE_FLASH/hf_cache\""
```

Install Miniconda at `$REMOTE_FLASH/miniconda3`. If you already have a working Miniconda tree elsewhere, point `$REMOTE_FLASH/miniconda3` at it.

Example reuse of an existing install:
```bash
ssh "$REMOTE_HOST" "ln -sfn /coc/pskynet6/$USER/miniconda3 \"$REMOTE_FLASH/miniconda3\""
```

Create the persistent environment once:
```bash
ssh "$REMOTE_HOST" "\"$REMOTE_FLASH/miniconda3/bin/conda\" create -y -n \"$REMOTE_ENV_NAME\" python=3.10"
```

Bootstrap the agent dependencies once by syncing `interface_agents/` to a bootstrap directory and installing from the shared requirements file:
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

The runtime path the backend needs is:
```text
<remote-flash>/miniconda3/envs/<env-name>/bin/python
```

### 4) Configure backend remote wiring
Edit `backend/.env` to match the one-time remote setup.

| Variable | Purpose |
|----------|---------|
| `LEGAL_CASE_CLUSTER_RUN_MODE` | `remote` for real cluster jobs, `spoof` for fixture-backed local testing |
| `LEGAL_CASE_CLUSTER_SSH_HOST` | SSH host for the SLURM head node |
| `LEGAL_CASE_CLUSTER_REMOTE_STAGE_ROOT` | Root directory where the backend creates per-run staged snapshots |
| `LEGAL_CASE_CLUSTER_REMOTE_PYTHON_PATH` | Absolute path to the persistent remote Python interpreter |
| `LEGAL_CASE_CLUSTER_REMOTE_HF_CACHE_DIR` | Shared Hugging Face cache directory on the head node |
| `LEGAL_CASE_CLUSTER_REMOTE_SLURM_BIN_DIR` | Directory that contains `sbatch`, `squeue`, and `sacct` |
| `LEGAL_CASE_CLUSTER_REMOTE_CONTROLLER_SCRIPT` | Checklist controller entrypoint relative to the staged run directory |
| `LEGAL_CASE_CLUSTER_SUMMARY_REMOTE_CONTROLLER_SCRIPT` | Summary controller entrypoint relative to the staged run directory |
| `LEGAL_CASE_CLUSTER_SLURM_PARTITION` | SLURM partition for checklist jobs |
| `LEGAL_CASE_CLUSTER_SLURM_QOS` | SLURM QoS for checklist jobs |
| `LEGAL_CASE_CLUSTER_SUMMARY_SLURM_PARTITION` | SLURM partition for summary jobs |
| `LEGAL_CASE_CLUSTER_SUMMARY_SLURM_QOS` | SLURM QoS for summary jobs |

The checked-in defaults in `backend/.env.example` assume:
- staged runs under `/coc/pskynet6/$USER/flash/interface_agent_runs`
- the persistent interpreter at `/coc/pskynet6/$USER/flash/miniconda3/envs/gavel-dev/bin/python`
- Hugging Face cache at `/coc/pskynet6/$USER/flash/hf_cache`

### 5) How remote execution works
The backend does not depend on a persistent remote checkout of this repository.

For every backend run:
1. The backend creates `<remote-stage-root>/<backend-run-id>/` on the head node.
2. The backend rsyncs the local `interface_agents/` tree into that directory.
3. The backend writes stage-local `.env` files into the staged checklist and summary agent directories.
4. Extraction launches from that staged snapshot.
5. Summary launches from the same staged snapshot after extraction completes.
6. Run artifacts remain in that stage directory until you clean them up manually.

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
LEGAL_CASE_CLUSTER_RUN_MODE=spoof
```

### Remote mode
Remote mode stages `interface_agents/` to the head node and dispatches real extraction and summary jobs through the agent controllers.

```bash
LEGAL_CASE_CLUSTER_RUN_MODE=remote
```

Remote mode requires:
- working `ssh` and `rsync` locally
- a reachable SLURM head node
- a persistent remote Python environment with the shared `interface_agents/requirements.txt` installed
- remote stage, cache, and SLURM paths configured correctly

## Notes
- The backend still uses the historical `LEGAL_CASE_` env prefix. Treat it as a legacy namespace only.
- Domain-specific behavior belongs in `backend/app/resources/` and `interface_agents/`, not in the generic UI flow or backend orchestration.
- `interface_agent_runs/` cleanup is manual. The backend keeps run directories in place so you can inspect the exact staged snapshot and artifacts for each run.
