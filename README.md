# Legal Case Summary Workspace

Full-stack prototype for an attorney-facing case summary editor. The React/Vite frontend gives writers a document-rich workspace, while the FastAPI backend handles document retrieval plus remote cluster-backed checklist extraction and summary generation.

## Repository Layout
- `frontend/` – React 19 + Vite workspace
- `backend/` – FastAPI service plus background jobs, LLM abstraction, Clearinghouse client stub, and structured schemas.
- `backend/app/data/` – Local SQLite database used for document/checklist caching (path via `LEGAL_CASE_DATABASE_URL`).
- `backend/app/resources/checklists/` – Prompt template and curated checklist metadata used by evidence extraction.
- `backend/logs/` – Rotating JSONL logs written by `app/logging_utils.py`, including every LLM request/response for auditing.
- `tools/`, `scratch/` – Local experimentation helpers (not part of the deployed app).

## Platform Capabilities
### Document ingestion & caching
- `GET /cases/{case_id}/documents` fetches documents from Clearinghouse.
- Remote pulls are cached on disk in SQLite (location set by `LEGAL_CASE_DATABASE_URL`) so repeated loads are instant and survive process restarts.
- The same endpoint prefetches LLM-derived checklists in the background and returns `checklist_status` (`pending`, `cached`, `empty`) so the UI can reflect readiness.

### Summary generation status
- Summary editing/versioning remains available in the UI.
- `POST /cases/{case_id}/summary` starts a remote cluster summary job.
- `GET /cases/{case_id}/summary/{job_id}` returns summary job status and the generated summary text on success.
- `GET /cases/summary/prompt` remains available for prompt-template workflow.

### Checklist extraction pipeline
- Evidence extraction runs over the authoritative documents (`app/services/checklists.py`) and executes only via the remote cluster controller.
- Extraction is cached per case in SQLite (path set by `LEGAL_CASE_DATABASE_URL`) so repeated loads avoid redundant extraction.
- Remote SLURM controller contract + operator runbook lives at `scratch/handoff/HANDOFF_to_remote.md` (includes SSH invocation mode, NDJSON event semantics, and artifact rsync flow).

### Conversational assistant status
- Chat is removed from both backend and frontend.
- Summary patching is still supported for local/manual edits and version history, but AI chat-assisted patch generation is not available.

### Attorney workspace (React)
- **Home screen** (`frontend/src/features/home/HomeScreen.jsx`): enter a case ID to open the workspace.
- **Summary panel**: shows the live draft, toggles between edit/read modes, tracks a local version history dropdown, and surfaces patch overlays you can click, preview, or revert. The AI generate button triggers remote cluster generation.
- **Checklist panel**: contrasts document coverage, outlines reasoning/evidence spans, and supports manual add/delete editing.
- **Documents panel**: renders full-text evidence, highlights referenced spans, and stays in sync with checklist-driven navigation.

## API Surface
| Method | Route | Description |
|--------|-------|-------------|
| `GET`  | `/health/pulse` | Simple readiness probe. |
| `GET`  | `/cases/{case_id}/documents` | Returns documents, optional prefetched checklist data, and checklist status metadata. |
| `POST` | `/cases/{case_id}/summary` | Starts a remote summary generation job. |
| `GET`  | `/cases/{case_id}/summary/{job_id}` | Polls summary generation status and returns output when complete. |
| `GET`  | `/cases/summary/prompt` | Returns the default summary prompt template. |
| `POST` | `/cases/{case_id}/checklist/start` | Starts remote extraction. |
| `GET`  | `/cases/{case_id}/checklist/status` | Polls remote extraction status. |

All schemas live under `backend/app/schemas/` and are enforced both inbound (FastAPI validation) and outbound (Pydantic models from the LLM layer).

## Running Locally
### Prerequisites
| Component | Requirement |
|-----------|-------------|
| Backend | Python 3.11+, `pip`, virtualenv. |
| Frontend | Node.js 18+ (any modern npm). |
| LLM providers | One of: OpenAI API key, or [Ollama](https://ollama.com/) with a pulled model (default `qwen3:8b`). |
| Optional | macOS/Linux shell, two terminal panes, `make` (optional). |

### Backend setup
```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # edit values as needed
python migrate_flat_db_to_sqlite.py  # one-time migration from flat JSON to SQLite
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
Notes:
- `LEGAL_CASE_DATABASE_URL` is required and defaults to a local SQLite file in `backend/app/data/legal_case.db` (see `backend/.env.example`).
- Run `python migrate_flat_db_to_sqlite.py` once before first startup if you want to import the existing flat DB caches.
- SQLite creates the database file automatically; no separate DB service needs to be started (just ensure the parent directory is writable).

### Frontend setup
```bash
cd frontend
npm install
cp .env.example .env             # optional; overrides API origin
npm run dev                      # launches on http://localhost:5173
```

### Local workflow
1. Start the FastAPI server.
2. Start `npm run dev` and open `http://localhost:5173`.
3. On the home screen, enter a case ID, then “Proceed to Summary Editor”.
4. Wait for checklist extraction to complete in the preparation page.
5. Edit summary/checklist/documents in workspace and generate summaries through the remote cluster.

## Configuration
### Backend environment (`LEGAL_CASE_*`)
| Variable | Purpose |
|----------|---------|
| `LEGAL_CASE_APP_NAME` | Display name in logs. |
| `LEGAL_CASE_ENVIRONMENT` | `development`/`production` (affects CORS + logging). |
| `LEGAL_CASE_USE_MOCK_LLM` | Force the deterministic mock backend (useful for UI testing). |
| `LEGAL_CASE_CONFIG_PATH` | Path to the JSON model config (defaults to `config/app.config.json`). |
| `LEGAL_CASE_DATABASE_URL` | SQLAlchemy database URL (SQLite file recommended for local use). |
| `OPENAI_API_KEY` | Required when `model.provider` is `openai`. |
| `LEGAL_CASE_CLEARINGHOUSE_API_KEY` | Enables the Clearinghouse HTTP client; required to fetch case documents. |

`backend/config/app.config.json` controls the active provider, model IDs, timeouts, and defaults (temperature, max tokens). Switch providers by editing `model.provider` and filling in the corresponding block—no code changes needed.

### Frontend environment
| Variable | Purpose |
|----------|---------|
| `VITE_BACKEND_URL` | Base URL for API requests (defaults to `http://localhost:8000`). |

### Data, assets, and logs
- API caches: SQLite DB at `LEGAL_CASE_DATABASE_URL` (default `backend/app/data/legal_case.db`).
- LLM/file logs: `backend/logs/llm-*.log`, `backend/logs/clearinghouse-*.log`, etc.
- One-time migration helper: `backend/migrate_flat_db_to_sqlite.py`.

## Using the Workspace Effectively
- **Versioning & patches**: Saved drafts are tracked in `useSummaryStore`’s `versionHistory`. The `SummaryPatchPanel` lists patches and lets you jump/revert as needed.
- **Checklist insights**: Checklist columns show status and evidence ranges, and allow manual curation.
Happy lawyering!
