# Backend Service

FastAPI service for the Multi-Document Summarization Interface.

## Quick Start
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Environment Variables (`.env`)
- `MULTI_DOCUMENT_DATABASE_URL` – SQLAlchemy database URL (e.g. `sqlite:///./app/data/legal_case.db`)
- `MULTI_DOCUMENT_CHECKLIST_START_ENABLED` – When `false`, checklist extraction start calls fail fast (debug switch)
- `MULTI_DOCUMENT_CLUSTER_RUN_MODE` – Backend execution mode: `remote` or `spoof`
- `MULTI_DOCUMENT_CLUSTER_SPOOF_EVENT_DELAY_SECONDS` – Optional per-event delay for spoof replay
- `MULTI_DOCUMENT_CLUSTER_SPOOF_EXTRACTION_FIXTURE_DIR` – Extraction spoof fixture directory
- `MULTI_DOCUMENT_CLUSTER_SPOOF_SUMMARY_FIXTURE_DIR` – Summary spoof fixture directory
- `MULTI_DOCUMENT_CLUSTER_SSH_HOST` – SSH host for the SLURM head node
- `MULTI_DOCUMENT_CLUSTER_REMOTE_STAGE_ROOT` – Remote root where the backend stages a fresh `interface_agents/` snapshot for each run
- `MULTI_DOCUMENT_CLUSTER_REMOTE_PYTHON_PATH` – Persistent remote python executable used to launch staged controllers
- `MULTI_DOCUMENT_CLUSTER_REMOTE_HF_CACHE_DIR` – Shared Hugging Face cache directory used by staged runs
- `MULTI_DOCUMENT_CLUSTER_REMOTE_SLURM_BIN_DIR` – Directory that contains `sbatch`, `squeue`, and `sacct`
- `MULTI_DOCUMENT_CLUSTER_REMOTE_CONTROLLER_SCRIPT` – Remote controller entrypoint (native path by default)
- `MULTI_DOCUMENT_CLUSTER_FOCUS_CONTEXT_TEMPLATE_PATH` – Checklist focus-context template file (supports placeholder `#RUN_TITLE`)
- `MULTI_DOCUMENT_CLUSTER_SUMMARY_REMOTE_CONTROLLER_SCRIPT` – Remote summary-agent controller entrypoint
- `MULTI_DOCUMENT_CLUSTER_SUMMARY_MODEL_NAME` – Default summary-agent model id
- `MULTI_DOCUMENT_CLUSTER_SUMMARY_MAX_STEPS` – Default summary-agent max steps
- `MULTI_DOCUMENT_CLUSTER_SUMMARY_REASONING_EFFORT` – Default summary-agent reasoning effort (`low|medium|high`)
- `MULTI_DOCUMENT_CLUSTER_SUMMARY_K_RECENT_TOOL_OUTPUTS` – Default tool-output history window
- `MULTI_DOCUMENT_CLUSTER_SUMMARY_PROMPT_CONFIG` – Optional default prompt config path
- `MULTI_DOCUMENT_CLUSTER_SUMMARY_FOCUS_CONTEXT_TEMPLATE_PATH` – Default summary focus-context template file (supports placeholders like `#RUN_TITLE`)

## Primary Endpoints
| Method | Route | Description |
|--------|-------|-------------|
| `POST` | `/runs` | Creates an empty run shell |
| `POST` | `/runs/{run_id}/upload-documents` | Uploads documents into an existing run |
| `GET`  | `/runs/defaults` | Returns canonical extraction and summary defaults |
| `GET`  | `/runs/{run_id}` | Returns run metadata and workflow state |
| `GET`  | `/runs/{run_id}/documents` | Returns uploaded documents for the run |
| `PUT`  | `/runs/{run_id}/extraction-config` | Updates extraction configuration |
| `POST` | `/runs/{run_id}/extraction/start` | Starts extraction for the run |
| `GET`  | `/runs/{run_id}/extraction/status` | Polls extraction status |
| `GET`  | `/runs/{run_id}/checklist` | Returns the current run checklist |
| `PUT`  | `/runs/{run_id}/checklist` | Persists checklist edits |
| `PUT`  | `/runs/{run_id}/summary-config` | Updates summary configuration |
| `POST` | `/runs/{run_id}/summary/start` | Starts summary generation for the run |
| `GET`  | `/runs/{run_id}/summary/status` | Polls summary status and returns summary text on success |
