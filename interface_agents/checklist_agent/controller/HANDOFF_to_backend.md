# Interface Agent Backend Handoff (Path Migration)

Consolidated checklist+summary migration handoff:
- `/coc/pskynet6/jzheng390/gavel/interface_agents/HANDOFF_to_backend.md`

This handoff describes how to switch checklist-extraction backend calls from the legacy target:
- `src/extract_checklist_from_documents/gavel_agent/...`

to the isolated target:
- `interface_agents/checklist_agent/...`

Date: 2026-04-05

## 0) Split Move Notice (Checklist + Summary)

The previous single-folder target:
- `interface_agent/...`

is now fully split into:
- Checklist extraction: `interface_agents/checklist_agent/...`
- Summary generation: `interface_agents/summary_agent/...`

Backend should route checklist jobs and summary jobs to different controller entrypoints.

## 1) Canonical New Targets

Backend should now call:
- Standard controller:
  - `/coc/pskynet6/jzheng390/gavel/interface_agents/checklist_agent/controller/run_controller.py`
- Native controller:
  - `/coc/pskynet6/jzheng390/gavel/interface_agents/checklist_agent/controller/run_controller_native.py`

Recommended working directory:
- `/coc/pskynet6/jzheng390/gavel`

Python interpreter (unchanged recommendation):
- `/coc/pskynet6/jzheng390/miniconda3/envs/gavel-dev/bin/python`

## 2) Old -> New Path Mapping

Controller script paths:
- OLD: `/coc/pskynet6/jzheng390/gavel/src/extract_checklist_from_documents/gavel_agent/controller/run_controller.py`
- NEW: `/coc/pskynet6/jzheng390/gavel/interface_agents/checklist_agent/controller/run_controller.py`

- OLD (intermediate): `/coc/pskynet6/jzheng390/gavel/interface_agent/controller/run_controller.py`
- NEW: `/coc/pskynet6/jzheng390/gavel/interface_agents/checklist_agent/controller/run_controller.py`

- OLD: `/coc/pskynet6/jzheng390/gavel/src/extract_checklist_from_documents/gavel_agent/controller/run_controller_native.py`
- NEW: `/coc/pskynet6/jzheng390/gavel/interface_agents/checklist_agent/controller/run_controller_native.py`

- OLD (intermediate): `/coc/pskynet6/jzheng390/gavel/interface_agent/controller/run_controller_native.py`
- NEW: `/coc/pskynet6/jzheng390/gavel/interface_agents/checklist_agent/controller/run_controller_native.py`

Run artifact root:
- OLD: `/coc/pskynet6/jzheng390/gavel/src/extract_checklist_from_documents/gavel_agent/controller/runs/<run_id>/`
- NEW: `/coc/pskynet6/jzheng390/gavel/interface_agents/checklist_agent/controller/runs/<run_id>/`

- OLD (intermediate): `/coc/pskynet6/jzheng390/gavel/interface_agent/controller/runs/<run_id>/`
- NEW: `/coc/pskynet6/jzheng390/gavel/interface_agents/checklist_agent/controller/runs/<run_id>/`

Controller request mirror path:
- OLD: `.../src/extract_checklist_from_documents/gavel_agent/controller/runs/<run_id>/request.json`
- NEW: `.../interface_agents/checklist_agent/controller/runs/<run_id>/request.json`

SLURM launcher scripts (resolved internally by controller):
- Standard: `/coc/pskynet6/jzheng390/gavel/interface_agents/checklist_agent/run_agent.sbatch`
- Native: `/coc/pskynet6/jzheng390/gavel/interface_agents/checklist_agent/run_agent_native.sbatch`

## 3) Runtime Configuration (.env)

`interface_agents/checklist_agent` now loads absolute paths from:
- `/coc/pskynet6/jzheng390/gavel/interface_agents/checklist_agent/.env`

Current configured values:
- `INTERFACE_AGENT_BASE_DIR=/coc/pskynet6/jzheng390/gavel/interface_agents/checklist_agent`
- `INTERFACE_AGENT_PYTHON_BIN=/coc/pskynet6/jzheng390/miniconda3/envs/gavel-dev/bin/python`
- `INTERFACE_AGENT_SLURM_BIN_DIR=/opt/slurm/Ubuntu-20.04/current/bin`
- HF cache env vars also set in `.env`

Important behavior:
- Controller auto-loads `interface_agents/checklist_agent/.env` by default.
- SBatch scripts also source `interface_agents/checklist_agent/.env` by default.
- You can override with env var `INTERFACE_AGENT_ENV_FILE=/abs/path/to/.env` if needed.

## 4) Backend Rewire Steps (Concrete)

Suggested constant migration in backend code:

```python
# BEFORE
CHECKLIST_CONTROLLER = "/coc/pskynet6/jzheng390/gavel/src/extract_checklist_from_documents/gavel_agent/controller/run_controller.py"
CHECKLIST_CONTROLLER_NATIVE = "/coc/pskynet6/jzheng390/gavel/src/extract_checklist_from_documents/gavel_agent/controller/run_controller_native.py"
CHECKLIST_RUNS_ROOT = "/coc/pskynet6/jzheng390/gavel/src/extract_checklist_from_documents/gavel_agent/controller/runs"

# AFTER
CHECKLIST_CONTROLLER = "/coc/pskynet6/jzheng390/gavel/interface_agents/checklist_agent/controller/run_controller.py"
CHECKLIST_CONTROLLER_NATIVE = "/coc/pskynet6/jzheng390/gavel/interface_agents/checklist_agent/controller/run_controller_native.py"
CHECKLIST_RUNS_ROOT = "/coc/pskynet6/jzheng390/gavel/interface_agents/checklist_agent/controller/runs"
```

1. Update backend constants that point to controller entrypoints.
- Set standard controller path to `.../interface_agents/checklist_agent/controller/run_controller.py`.
- Set native controller path to `.../interface_agents/checklist_agent/controller/run_controller_native.py`.

2. Keep the same controller mode flags.
- For production checklist flow: `--mode slurm_extract_strategy`
- Native vs custom is still selected by which controller script path you invoke.

3. Update any artifact polling/ingestion root assumptions.
- Replace all hardcoded legacy runs-root references with:
  - `/coc/pskynet6/jzheng390/gavel/interface_agents/checklist_agent/controller/runs/`

4. Keep request JSON schema unchanged.
- Payload contract is unchanged from current checklist controller contract.
- No new required JSON fields were introduced for this migration.

5. Optional but recommended: pass explicit env-file pointer from backend command runner.
- Add env var:
  - `INTERFACE_AGENT_ENV_FILE=/coc/pskynet6/jzheng390/gavel/interface_agents/checklist_agent/.env`
- This avoids ambiguity if working directory changes.

## 5) Updated Command Templates

Standard scaffold (strategy mode):
```bash
cat /path/to/request.json | \
/coc/pskynet6/jzheng390/miniconda3/envs/gavel-dev/bin/python \
/coc/pskynet6/jzheng390/gavel/interface_agents/checklist_agent/controller/run_controller.py \
--mode slurm_extract_strategy --poll-seconds 2 --max-wait-seconds 21600
```

Native scaffold (strategy mode):
```bash
cat /path/to/request.json | \
/coc/pskynet6/jzheng390/miniconda3/envs/gavel-dev/bin/python \
/coc/pskynet6/jzheng390/gavel/interface_agents/checklist_agent/controller/run_controller_native.py \
--mode slurm_extract_strategy --poll-seconds 2 --max-wait-seconds 21600
```

Smoke test (quick backend health check):
```bash
/coc/pskynet6/jzheng390/miniconda3/envs/gavel-dev/bin/python \
/coc/pskynet6/jzheng390/gavel/interface_agents/checklist_agent/controller/run_controller.py \
--mode smoke --request-id backend_migration_smoke --ticks 2 --tick-seconds 1
```

## 6) Artifact Contract After Migration

Contract shape is unchanged; only root directory moved.

On completion, backend should still ingest from:
- `result_payload.json` (authoritative payload)
- `manifest.json`
- `checklist.json`
- `checklist.ndjson`
- `document_map.json`

New absolute locations are under:
- `/coc/pskynet6/jzheng390/gavel/interface_agents/checklist_agent/controller/runs/<run_id>/...`

## 7) Backend Acceptance Checklist

1. Smoke command emits `started` then `completed`.
2. Strategy command emits `request_validated` and `slurm_submitted` with no path errors.
3. Backend can resolve `run_dir` and `result_payload_path` from NDJSON `completed` event.
4. Backend no longer references `src/extract_checklist_from_documents/gavel_agent/controller/runs`.

## 8) Summary Agent Redirect (Companion Route)

Summary controller path:
- `/coc/pskynet6/jzheng390/gavel/interface_agents/summary_agent/controller/run_controller.py`

Summary mode:
- `--mode slurm_summarize_agent`

Summary runs root:
- `/coc/pskynet6/jzheng390/gavel/interface_agents/summary_agent/controller/runs`

Summary smoke command:
```bash
/coc/pskynet6/jzheng390/miniconda3/envs/gavel-dev/bin/python \
/coc/pskynet6/jzheng390/gavel/interface_agents/summary_agent/controller/run_controller.py \
--mode smoke --request-id backend_summary_migration_smoke --ticks 2 --tick-seconds 1
```

Summary production scaffold:
```bash
cat /path/to/summary_request.json | \
/coc/pskynet6/jzheng390/miniconda3/envs/gavel-dev/bin/python \
/coc/pskynet6/jzheng390/gavel/interface_agents/summary_agent/controller/run_controller.py \
--mode slurm_summarize_agent --poll-seconds 2 --max-wait-seconds 21600
```

Summary success checks:
1. NDJSON emits `request_validated`, `slurm_submitted`, then terminal `completed`.
2. `completed.data.summary_path` and `completed.data.result_payload_path` exist.
3. `summary_path` JSON includes field `summary` (canonical text for ingestion).
