# Interface Agents Backend Handoff (Checklist + Summary Split)

Date: 2026-04-05

## 1) Migration Summary

Deprecated roots:
- `/coc/pskynet6/jzheng390/gavel/src/extract_checklist_from_documents/gavel_agent/...`
- `/coc/pskynet6/jzheng390/gavel/src/summarize_documents/summary_agent/...`
- `/coc/pskynet6/jzheng390/gavel/interface_agent/...` (intermediate)

Current roots:
- Checklist agent: `/coc/pskynet6/jzheng390/gavel/interface_agents/checklist_agent/...`
- Summary agent: `/coc/pskynet6/jzheng390/gavel/interface_agents/summary_agent/...`

## 2) Canonical Entrypoints

Checklist (standard):
- `/coc/pskynet6/jzheng390/gavel/interface_agents/checklist_agent/controller/run_controller.py`
- mode: `--mode slurm_extract_strategy`

Checklist (native):
- `/coc/pskynet6/jzheng390/gavel/interface_agents/checklist_agent/controller/run_controller_native.py`
- mode: `--mode slurm_extract_strategy`

Summary:
- `/coc/pskynet6/jzheng390/gavel/interface_agents/summary_agent/controller/run_controller.py`
- mode: `--mode slurm_summarize_agent`

Working directory:
- `/coc/pskynet6/jzheng390/gavel`

Python:
- `/coc/pskynet6/jzheng390/miniconda3/envs/gavel-dev/bin/python`

## 3) Backend Constant Redirects

```python
# Checklist
CHECKLIST_CONTROLLER = "/coc/pskynet6/jzheng390/gavel/interface_agents/checklist_agent/controller/run_controller.py"
CHECKLIST_CONTROLLER_NATIVE = "/coc/pskynet6/jzheng390/gavel/interface_agents/checklist_agent/controller/run_controller_native.py"
CHECKLIST_RUNS_ROOT = "/coc/pskynet6/jzheng390/gavel/interface_agents/checklist_agent/controller/runs"

# Summary
SUMMARY_CONTROLLER = "/coc/pskynet6/jzheng390/gavel/interface_agents/summary_agent/controller/run_controller.py"
SUMMARY_RUNS_ROOT = "/coc/pskynet6/jzheng390/gavel/interface_agents/summary_agent/controller/runs"
```

## 4) Optional Env Pins

Recommended env for backend shell runner:
- `INTERFACE_AGENT_ENV_FILE=/coc/pskynet6/jzheng390/gavel/interface_agents/checklist_agent/.env`
- `INTERFACE_SUMMARY_AGENT_ENV_FILE=/coc/pskynet6/jzheng390/gavel/interface_agents/summary_agent/.env`
- `INTERFACE_CHECKLIST_AGENT_BASE_DIR=/coc/pskynet6/jzheng390/gavel/interface_agents/checklist_agent`

## 5) Smoke Tests

Checklist smoke:
```bash
/coc/pskynet6/jzheng390/miniconda3/envs/gavel-dev/bin/python \
/coc/pskynet6/jzheng390/gavel/interface_agents/checklist_agent/controller/run_controller.py \
--mode smoke --request-id backend_checklist_migration_smoke --ticks 2 --tick-seconds 1
```

Summary smoke:
```bash
/coc/pskynet6/jzheng390/miniconda3/envs/gavel-dev/bin/python \
/coc/pskynet6/jzheng390/gavel/interface_agents/summary_agent/controller/run_controller.py \
--mode smoke --request-id backend_summary_migration_smoke --ticks 2 --tick-seconds 1
```

## 6) End-to-End Test Scaffolds

Checklist standard:
```bash
cat /path/to/checklist_request.json | \
/coc/pskynet6/jzheng390/miniconda3/envs/gavel-dev/bin/python \
/coc/pskynet6/jzheng390/gavel/interface_agents/checklist_agent/controller/run_controller.py \
--mode slurm_extract_strategy --poll-seconds 2 --max-wait-seconds 21600
```

Checklist native:
```bash
cat /path/to/checklist_request.json | \
/coc/pskynet6/jzheng390/miniconda3/envs/gavel-dev/bin/python \
/coc/pskynet6/jzheng390/gavel/interface_agents/checklist_agent/controller/run_controller_native.py \
--mode slurm_extract_strategy --poll-seconds 2 --max-wait-seconds 21600
```

Summary:
```bash
cat /path/to/summary_request.json | \
/coc/pskynet6/jzheng390/miniconda3/envs/gavel-dev/bin/python \
/coc/pskynet6/jzheng390/gavel/interface_agents/summary_agent/controller/run_controller.py \
--mode slurm_summarize_agent --poll-seconds 2 --max-wait-seconds 21600
```

## 7) Acceptance Criteria

1. Smoke runs emit `started` then `completed`.
2. E2E runs emit `request_validated`, `slurm_submitted`, terminal `completed`.
3. Checklist completion points to `.../interface_agents/checklist_agent/controller/runs/<run_id>/...`.
4. Summary completion points to `.../interface_agents/summary_agent/controller/runs/<run_id>/...`.
5. Summary ingestion reads canonical text from `summary_path` JSON field `summary`.
