# Backend Service

FastAPI service that powers the Legal Case Summary Workspace.

## Quick Start
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Environment Variables (`.env`)
- `LEGAL_CASE_DATABASE_URL` – SQLAlchemy database URL (e.g. `sqlite:///./app/data/legal_case.db`)
- `LEGAL_CASE_CHECKLIST_START_ENABLED` – When `false`, checklist extraction start calls fail fast (debug switch)
- `LEGAL_CASE_CLUSTER_RUN_MODE` – Backend execution mode: `remote` or `spoof`
- `LEGAL_CASE_CLUSTER_SPOOF_EVENT_DELAY_SECONDS` – Optional per-event delay for spoof replay
- `LEGAL_CASE_CLUSTER_SPOOF_EXTRACTION_FIXTURE_DIR` – Extraction spoof fixture directory
- `LEGAL_CASE_CLUSTER_SPOOF_SUMMARY_FIXTURE_DIR` – Summary spoof fixture directory
- `LEGAL_CASE_CLUSTER_SSH_HOST` – SSH host for remote extraction controller
- `LEGAL_CASE_CLUSTER_REMOTE_REPO_DIR` – Remote repo root for controller invocation
- `LEGAL_CASE_CLUSTER_REMOTE_PYTHON_PATH` – Remote python executable used to launch controller
- `LEGAL_CASE_CLUSTER_REMOTE_CONTROLLER_SCRIPT` – Remote controller entrypoint (native path by default)
- `LEGAL_CASE_CLUSTER_FOCUS_CONTEXT_TEMPLATE_PATH` – Checklist focus-context template file (supports placeholder `#CASE_TITLE`)
- `LEGAL_CASE_CLUSTER_SUMMARY_REMOTE_CONTROLLER_SCRIPT` – Remote summary-agent controller entrypoint
- `LEGAL_CASE_CLUSTER_SUMMARY_MODEL_NAME` – Default summary-agent model id
- `LEGAL_CASE_CLUSTER_SUMMARY_MAX_STEPS` – Default summary-agent max steps
- `LEGAL_CASE_CLUSTER_SUMMARY_REASONING_EFFORT` – Default summary-agent reasoning effort (`low|medium|high`)
- `LEGAL_CASE_CLUSTER_SUMMARY_K_RECENT_TOOL_OUTPUTS` – Default tool-output history window
- `LEGAL_CASE_CLUSTER_SUMMARY_PROMPT_CONFIG` – Optional default prompt config path
- `LEGAL_CASE_CLUSTER_SUMMARY_FOCUS_CONTEXT_TEMPLATE_PATH` – Default summary focus-context template file (supports placeholders like `#CASE_TITLE`)

## Primary Endpoints
| Method | Route | Description |
|--------|-------|-------------|
| `GET`  | `/cases/{case_id}/documents` | Returns catalogued documents with content |
| `POST` | `/cases/{case_id}/summary` | Starts summary generation using the configured run mode |
| `GET`  | `/cases/{case_id}/summary/{job_id}` | Polls summary job status and output |
| `GET`  | `/cases/{case_id}/summary/prompt` | Returns default summary prompt template |
| `POST` | `/cases/{case_id}/checklist/start` | Starts checklist extraction using the configured run mode |
| `GET`  | `/cases/{case_id}/checklist/status` | Polls extraction status |
