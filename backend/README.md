# Backend Service

The backend is a run-centric FastAPI service for the Multi-Document Summarization Interface. It owns document ingestion, run state, canonical extraction and summary defaults, cluster job orchestration, result ingestion, and progress reporting.

This service assumes a single backend process. Queue locks, background tasks, and the event manager are all in-process.

## Quick Start
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## What The Backend Owns
- Create and update runs.
- Accept uploaded plain-text documents and persist them locally.
- Serve the canonical default extraction and summary configuration for new runs.
- Validate and persist user-edited extraction config, checklist edits, and summary config.
- Start extraction and summary generation as background tasks.
- Serialize all long-running cluster-backed work through one shared queue.
- Stage `interface_agents/` to the SLURM head node for each backend run.
- Stream controller progress back into the run record.
- Pull controller artifacts back into the backend and persist extracted checklist data and generated summary text.
- Replay recorded fixtures in spoof mode without touching the cluster.

## Backend Design Principles
- Run-centric state: every workflow is keyed by a backend `run_id`, not by a global corpus or case store.
- Canonical defaults live in backend resources: the UI starts from backend-provided checklist spec and focus-context templates.
- Fail fast on misconfiguration: startup validates the active execution mode and required local prerequisites.
- Reproducible remote execution: each backend run stages a fresh `interface_agents/` snapshot to the cluster.
- Process-local orchestration: background tasks and queue locks are intentionally simple and local to one backend process.

## Subsystems
### API Layer
Public routes live in:
- `app/api/routes/runs.py`
- `app/api/routes/health.py`
- `app/api/router.py`

The live API surface is intentionally small, as this backend is intended to be lightweight and simple:
- `/health/pulse`
- `/runs`
- `/runs/{run_id}/...`

### Workflow Service
`app/services/runs.py` is the central orchestration layer.

It is responsible for:
- creating empty runs and upload-backed runs
- normalizing and persisting extraction and summary config
- enforcing workflow-stage transitions
- starting extraction and summary jobs through FastAPI `BackgroundTasks`
- updating extraction progress, summary progress, and final run state
- translating stored extraction output into the checklist editing shape used by the frontend
- validating and persisting checklist edits back into the stored evidence collection

This file is the backend's main application service. If you want to understand how the product flow works, start there.

### Persistence Layer
The persistence split is:
- `app/db/models.py`: SQLAlchemy models
- `app/db/session.py`: engine/session factory and `init_db()`
- `app/data/run_store.py`: storage adapter used by the workflow service

Note: The backend does not use migrations right now for simplicity. On startup it calls `Base.metadata.create_all(...)` from `app/db/session.py`.

#### Table: `runs`
This is the primary workflow table. There is one row per backend run. It stores the run's human-facing identity, its editable configuration, the current workflow stage, and the full extraction and summary job state.

| Column | Purpose |
|--------|---------|
| `id` | Backend-generated `run_id`. Primary key used by the API and frontend route `/run/<run_id>`. |
| `source_type` | How the corpus entered the backend. Today this is effectively the document-ingestion mode for the run. |
| `title` | Human-facing run title shown in the UI and injected into focus-context templates. |
| `created_at` | Run creation timestamp stored as an ISO-like string. |
| `extraction_config_json` | Canonical extraction configuration persisted as JSON. This is what the user edits on the setup page before extraction. |
| `summary_config_json` | Canonical summary configuration persisted as JSON. This is what the user edits on the setup page before summary generation. |
| `workflow_stage` | Current UI/workflow stage for the run, such as `setup`, `extraction_wait`, `review`, `summary_wait`, or `workspace`. |
| `extraction_status` | High-level extraction status, for example `not_started`, `queued`, `running`, `succeeded`, or `failed`. |
| `extraction_error` | Final extraction failure message, if extraction terminates unsuccessfully. |
| `extraction_progress_json` | Latest extraction progress event payload as JSON. The frontend polls this to render live state during extraction. |
| `extraction_result_json` | Full normalized extraction result payload persisted after successful ingestion. This is the backend's stored evidence collection. |
| `extraction_remote_run_id` | Remote controller `run_id` for the extraction controller run. Useful when tracing remote artifacts and logs. |
| `extraction_remote_job_id` | Most relevant SLURM job id for extraction. This is typically the last submitted or active job id reported back by the controller. |
| `extraction_remote_output_dir` | Remote directory containing extraction controller artifacts for this run. |
| `extraction_manifest_path` | Absolute remote or staged path to the extraction manifest file returned by the controller. |
| `extraction_result_payload_path` | Absolute remote or staged path to the extraction result payload JSON returned by the controller. |
| `extraction_checklist_ndjson_path` | Absolute remote or staged path to the checklist NDJSON artifact emitted by extraction. |
| `summary_status` | High-level summary status, for example `not_started`, `queued`, `running`, `succeeded`, or `failed`. |
| `summary_error` | Final summary failure message, if summary generation terminates unsuccessfully. |
| `summary_progress_json` | Latest summary progress event payload as JSON. The frontend polls this to render live state during summary generation. |
| `summary_result_json` | Full normalized summary result payload persisted after successful ingestion. |
| `summary_text` | Current working summary text shown in the final workspace. This begins with generated summary output and can then be user-edited. |
| `summary_remote_run_id` | Remote controller `run_id` for the summary controller run. |
| `summary_remote_job_id` | Most relevant SLURM job id for summary generation. |
| `summary_remote_output_dir` | Remote directory containing summary controller artifacts for this run. |
| `summary_manifest_path` | Absolute remote or staged path to the summary manifest file returned by the controller. |
| `summary_result_payload_path` | Absolute remote or staged path to the summary result payload JSON returned by the controller. |
| `summary_summary_path` | Absolute remote or staged path to the generated summary text artifact returned by the controller. |

#### Table: `run_documents`
This table stores the document corpus attached to a run. There is one row per document, keyed by `(run_id, document_id)`. The backend uses it as the source of truth for later extraction and summary request construction.

| Column | Purpose |
|--------|---------|
| `run_id` | Foreign key back to `runs.id`. Associates the document with one run. |
| `document_id` | Stable per-run document identifier. This is what evidence pointers and controller payloads refer to. |
| `title` | Display title for the document. Used in the UI and controller request payloads. |
| `type` | User- or manifest-supplied document type label. |
| `description` | Optional free-text description for the document. |
| `source` | Optional source label describing where the document came from. |
| `ecf_number` | Optional original filing identifier field. It is retained as generic metadata even though the app is no longer domain-specific. |
| `date` | Optional document date string. Passed through to the controller payload if present. |
| `is_docket` | Boolean flag used to distinguish docket-like entries from ordinary documents. |
| `content` | Full plain-text document body stored in the database. This is the text sent to the extraction and summary controllers. |

### Queue And Concurrency Control
There are two in-memory locks that matter:
- `app/services/cluster_queue.py`: `_CLUSTER_RUN_LOCK`
- `app/services/runs.py`: `_start_lock`

Their roles are different:
- `_start_lock` prevents duplicate start requests from racing against each other while run state is being reset and queued.
- `_CLUSTER_RUN_LOCK` serializes all long-running extraction and summary jobs across the entire backend process.

That queue lock is shared by both extraction and summary. If one run is extracting, another run's summary job waits. This is the backend-side guarantee that only one cluster-backed job is launched at a time from this interface process.

Important constraint:
- this lock is process-local, not distributed
- if you run multiple backend processes, each process gets its own queue lock

### Execution Adapters
The backend has one engine interface for extraction and one for summary:
- `app/services/checklist_engines.py`
- `app/services/summary_engines.py`

Each engine has two implementations:
- `cluster`: real remote execution through SLURM controllers
- `spoof`: fixture-backed replay for UI and integration testing

The selection is controlled by `MULTI_DOCUMENT_CLUSTER_RUN_MODE`.

### Remote Cluster Execution
Remote execution is implemented in:
- `app/services/cluster_extraction.py`
- `app/services/cluster_summary.py`
- `app/services/remote_stage.py`
- `app/services/summary_agent_payload.py`

The remote execution flow is:
1. Validate local prerequisites at backend startup.
2. When a run starts, create `<remote_stage_root>/<backend_run_id>/` on the head node.
3. Rsync the local `interface_agents/` tree into that directory.
4. Generate stage-local `.env` files for the checklist and summary agents.
5. Write `stage_manifest.json` that records the staged code snapshot and local git state.
6. SSH into the head node and launch the controller from the staged snapshot.
7. Stream controller stdout as the progress/event contract.
8. Log controller stderr for diagnostics.
9. Pull the result artifacts back with `rsync` when the controller completes.
10. Persist the ingested result into the run store.

The extraction and summary controllers both run from the same staged snapshot for a given backend run.

### Spoof Replay
Spoof mode is implemented in `app/services/spoof_replay.py`.

Spoof mode does three things:
- validates that the configured fixture directory exists and has the required files
- validates that the requested `corpus_id` and document ids match the fixture request payload
- replays recorded NDJSON events through the same progress callbacks used by live runs

That means the frontend sees realistic progress/state transitions even when no real cluster work is happening. Useful when attempting to make UI changes that you don't want to have trigger live runs.

### Default Resource Loaders
Backend-owned defaults live in:
- `app/resources/checklists/remote_checklist_spec.individual.json`
- `app/resources/checklists/focus_context.template.txt`
- `app/resources/summary/focus_context.template.txt`

The code that loads and validates them lives in:
- `app/services/cluster_checklist_spec.py`
- `app/services/cluster_focus_context.py`
- `app/services/summary_focus_context.py`

These modules are the source of truth for:
- checklist spec validation
- placeholder substitution such as `#RUN_TITLE`
- canonical extraction and summary defaults served to the frontend

### Eventing And Logs
Structured backend eventing lives in `app/eventing.py`.

The event system fans out to three consumers:
- file log consumer
- console log consumer
- Unix socket consumer

Startup wiring happens in `app/main.py`:
- initialize DB
- initialize event system
- validate execution prerequisites

By default the backend writes file logs to `backend/logs/` and exposes a Unix socket at the path configured by `MULTI_DOCUMENT_IPC_SOCKET_PATH`. The purpose of this socket is for user-coded log-ingesting applications to be able to view backend logs live, for example to track SLURM scheduling flow correctness, or track checklist or summary runs as they occur. Basic ones are packaged in tools/ but you can write new ones as you desire relatively easily.

## Run Lifecycle
### 1. Create The Run Shell
`POST /runs` creates an empty run with backend defaults and no documents.

### 2. Upload Documents
`POST /runs/{run_id}/upload-documents` parses the multipart upload, validates the manifest, decodes `.txt` files as UTF-8, normalizes document metadata, sorts the documents, and persists them into `run_documents`.

Manual upload is the current live ingestion path.

### 3. Load Defaults Or Edit Config
`GET /runs/defaults` returns the canonical extraction and summary config. The frontend can then update either config through:
- `PUT /runs/{run_id}/extraction-config`
- `PUT /runs/{run_id}/summary-config`

### 4. Start Extraction
`POST /runs/{run_id}/extraction/start`:
- checks that documents exist
- resets old extraction and summary state for the run
- marks extraction queued
- moves the workflow stage to `extraction_wait`
- schedules `_run_extraction_job()` as a background task

`_run_extraction_job()` then:
- renders the extraction focus template
- validates the checklist spec
- acquires the shared cluster queue lock
- chooses the active extraction engine
- streams progress events into the run store
- persists the final evidence collection on success
- moves the workflow stage to `review`

### 5. Review And Edit Checklist
The checklist returned by the extraction engine is stored as an `EvidenceCollection` JSON payload.

The frontend reads it through `GET /runs/{run_id}/checklist` as a category/value editing view. The backend translates between:
- stored flat evidence items
- UI category/value entries with document ids and offsets

Checklist edits are persisted through `PUT /runs/{run_id}/checklist`.

### 6. Start Summary Generation
`POST /runs/{run_id}/summary/start`:
- requires completed extraction output
- resets prior summary state
- marks summary queued
- moves the workflow stage to `summary_wait`
- schedules `_run_summary_job()` as a background task

`_run_summary_job()` then:
- rebuilds summary request input from stored run documents and stored checklist edits
- renders the summary focus template
- acquires the same shared cluster queue lock
- chooses the active summary engine
- persists summary text and summary artifacts on success
- moves the workflow stage to `workspace`

### 7. Persist And Revisit
The run record remains the source of truth after generation. Revisiting `/run/<run_id>` in the frontend reloads:
- run metadata and stage
- documents
- extraction config
- summary config
- checklist state
- summary text

## Environment Variables
The backend reads `.env` with the prefix `MULTI_DOCUMENT_`.

Important note:
- path values are read literally by the backend and by the staged agent `.env` files
- do not rely on shell expansion inside `.env`
- use concrete absolute paths for live runs

### Core App Settings
| Variable | Purpose |
|----------|---------|
| `MULTI_DOCUMENT_APP_NAME` | Human-readable backend service name used in logs and startup reporting. |
| `MULTI_DOCUMENT_ENVIRONMENT` | Free-form environment label such as `development` or `production`. Mainly useful for operators and logs. |
| `MULTI_DOCUMENT_DATABASE_URL` | SQLAlchemy database URL for the run store. The default repo setup uses SQLite. |
| `MULTI_DOCUMENT_EVENT_LOG_DIR` | Directory where file-backed backend event logs are written. |
| `MULTI_DOCUMENT_EVENT_LOG_PREFIX` | Filename prefix for event log files created under `MULTI_DOCUMENT_EVENT_LOG_DIR`. |
| `MULTI_DOCUMENT_IPC_SOCKET_PATH` | Unix socket path used by the backend event fanout so external tools can consume live backend logs. |

### Execution Mode
| Variable | Purpose |
|----------|---------|
| `MULTI_DOCUMENT_CLUSTER_RUN_MODE` | Selects the active execution adapter. Use `remote` for real SLURM-backed runs and `spoof` for fixture replay. |
| `MULTI_DOCUMENT_CLUSTER_SPOOF_EVENT_DELAY_SECONDS` | Optional artificial delay inserted between replayed spoof events to slow the UI down to a human-readable pace. |
| `MULTI_DOCUMENT_CLUSTER_SPOOF_EXTRACTION_FIXTURE_DIR` | Directory containing the extraction spoof fixture files used when run mode is `spoof`. |
| `MULTI_DOCUMENT_CLUSTER_SPOOF_SUMMARY_FIXTURE_DIR` | Directory containing the summary spoof fixture files used when run mode is `spoof`. |

### Remote Staging
| Variable | Purpose |
|----------|---------|
| `MULTI_DOCUMENT_CLUSTER_SSH_HOST` | SSH target for the SLURM head node where the backend stages code and launches controllers. |
| `MULTI_DOCUMENT_CLUSTER_REMOTE_STAGE_ROOT` | Remote parent directory under which the backend creates one staged snapshot directory per backend run. |
| `MULTI_DOCUMENT_CLUSTER_REMOTE_PYTHON_PATH` | Absolute path to the already-provisioned Python interpreter on the remote cluster. The backend writes this into staged agent `.env` files and uses it for controller execution. |
| `MULTI_DOCUMENT_CLUSTER_REMOTE_HF_CACHE_DIR` | Absolute remote Hugging Face cache directory shared by staged runs. |
| `MULTI_DOCUMENT_CLUSTER_REMOTE_SLURM_BIN_DIR` | Absolute directory containing `sbatch`, `squeue`, `sacct`, and other SLURM binaries on the head node. |
| `MULTI_DOCUMENT_CLUSTER_REMOTE_CONTROLLER_SCRIPT` | Path, relative to the staged remote snapshot root, of the extraction controller entrypoint. |
| `MULTI_DOCUMENT_CLUSTER_SUMMARY_REMOTE_CONTROLLER_SCRIPT` | Path, relative to the staged remote snapshot root, of the summary controller entrypoint. |
| `MULTI_DOCUMENT_CLUSTER_POLL_SECONDS` | Poll interval used by the backend while it waits on remote controller completion and artifact availability. |
| `MULTI_DOCUMENT_CLUSTER_MAX_WAIT_SECONDS` | Maximum wall-clock time the backend will wait for one remote controller run before timing out. |

### Extraction Defaults
| Variable | Purpose |
|----------|---------|
| `MULTI_DOCUMENT_CLUSTER_MODEL_NAME` | Default extraction model identifier passed through to the remote checklist controller. |
| `MULTI_DOCUMENT_CLUSTER_CHECKLIST_SPEC_PATH` | Backend-local path to the canonical extraction checklist spec JSON used to seed new runs. |
| `MULTI_DOCUMENT_CLUSTER_FOCUS_CONTEXT_TEMPLATE_PATH` | Backend-local path to the extraction focus-context template used to seed new runs and render request payloads. |
| `MULTI_DOCUMENT_CLUSTER_RESUME` | Resume flag forwarded to the extraction controller. Keep this `false` unless you intentionally want controller-side resume behavior. |
| `MULTI_DOCUMENT_CLUSTER_DEBUG` | Debug flag forwarded to the extraction controller for extra controller-side diagnostics. |
| `MULTI_DOCUMENT_CLUSTER_SLURM_PARTITION` | Default SLURM partition for extraction jobs. |
| `MULTI_DOCUMENT_CLUSTER_SLURM_QOS` | Default SLURM QoS for extraction jobs. |

### Summary Defaults
| Variable | Purpose |
|----------|---------|
| `MULTI_DOCUMENT_CLUSTER_SUMMARY_MODEL_NAME` | Default summary model identifier passed through to the remote summary controller. |
| `MULTI_DOCUMENT_CLUSTER_SUMMARY_MAX_STEPS` | Default maximum step budget for generated summary runs. This seeds new runs and can be overridden per run in the UI. |
| `MULTI_DOCUMENT_CLUSTER_SUMMARY_REASONING_EFFORT` | Default reasoning level for summary generation. This seeds new runs and can be overridden per run in the UI. |
| `MULTI_DOCUMENT_CLUSTER_SUMMARY_K_RECENT_TOOL_OUTPUTS` | Summary-agent runtime tuning knob controlling how many recent tool outputs the summary runtime keeps in context. |
| `MULTI_DOCUMENT_CLUSTER_SUMMARY_PROMPT_CONFIG` | Optional backend-side override for the summary prompt configuration file. Leave empty to use the controller's default prompt config. |
| `MULTI_DOCUMENT_CLUSTER_SUMMARY_FOCUS_CONTEXT_TEMPLATE_PATH` | Backend-local path to the summary focus-context template used to seed new runs and render summary requests. |
| `MULTI_DOCUMENT_CLUSTER_SUMMARY_SLURM_PARTITION` | Default SLURM partition for summary jobs. |
| `MULTI_DOCUMENT_CLUSTER_SUMMARY_SLURM_QOS` | Default SLURM QoS for summary jobs. |

## Key Files And Why They Matter
| Path | Responsibility |
|------|----------------|
| `app/main.py` | App startup and shutdown wiring |
| `app/api/routes/runs.py` | Public run-centric HTTP API |
| `app/services/runs.py` | Main workflow orchestration service |
| `app/data/run_store.py` | Persistence adapter over SQLAlchemy models |
| `app/db/models.py` | `runs` and `run_documents` schema |
| `app/services/cluster_queue.py` | Shared in-process queue lock |
| `app/services/checklist_engines.py` | Extraction engine selection (`cluster` vs `spoof`) |
| `app/services/summary_engines.py` | Summary engine selection (`cluster` vs `spoof`) |
| `app/services/cluster_extraction.py` | Remote extraction controller integration |
| `app/services/cluster_summary.py` | Remote summary controller integration |
| `app/services/remote_stage.py` | Per-run remote staging and generated `.env` overlay |
| `app/services/cluster_checklist_spec.py` | Checklist spec loading and validation |
| `app/services/cluster_focus_context.py` | Extraction focus template loading and placeholder rendering |
| `app/services/summary_focus_context.py` | Summary focus template loading and placeholder rendering |
| `app/services/summary_agent_payload.py` | Summary controller request payload builder |
| `app/services/spoof_replay.py` | Fixture-backed replay mode |
| `app/eventing.py` | Structured event fanout to log, console, and socket |

## Tests
The backend test suite focuses on:
- cluster extraction request building and artifact ingestion
- cluster summary payload building and artifact ingestion
- remote stage generation
- spoof replay behavior
- focus-context placeholder rendering
- checklist spec validation

Representative tests:
- `tests/test_cluster_extraction.py`
- `tests/test_cluster_summary.py`
- `tests/test_remote_stage.py`
- `tests/test_spoof_engines.py`
- `tests/test_cluster_focus_context.py`
- `tests/test_summary_focus_context.py`
- `tests/test_cluster_checklist_spec.py`
- `tests/test_summary_agent_payload.py`
