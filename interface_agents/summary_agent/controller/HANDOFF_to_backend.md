# Summary Agent Controller Handoff Contract

Consolidated checklist+summary migration handoff:
- `/coc/pskynet6/jzheng390/gavel/interface_agents/HANDOFF_to_backend.md`

Date: 2026-04-05

## 0) Split Move Notice (Checklist + Summary)

The previous single-folder target:
- `interface_agent/...`

has been replaced by split agent roots:
- Checklist extraction: `interface_agents/checklist_agent/...`
- Summary generation: `interface_agents/summary_agent/...`

For summary jobs, backend must call only the summary controller under:
- `interface_agents/summary_agent/controller/run_controller.py`

## 0.1) Path Redirect Map (Summary)

Controller script:
- OLD: `/coc/pskynet6/jzheng390/gavel/src/summarize_documents/summary_agent/controller/run_controller.py`
- OLD (intermediate): `/coc/pskynet6/jzheng390/gavel/interface_agent/controller/run_controller.py`
- NEW: `/coc/pskynet6/jzheng390/gavel/interface_agents/summary_agent/controller/run_controller.py`

Run root:
- OLD: `/coc/pskynet6/jzheng390/gavel/src/summarize_documents/summary_agent/controller/runs/<run_id>/`
- OLD (intermediate): `/coc/pskynet6/jzheng390/gavel/interface_agent/controller/runs/<run_id>/`
- NEW: `/coc/pskynet6/jzheng390/gavel/interface_agents/summary_agent/controller/runs/<run_id>/`

Backend entrypoint:
- `interface_agents/summary_agent/controller/run_controller.py`

Mode for production-style runs:
- `--mode slurm_summarize_agent`

## 1) Invocation

Working directory:
- `/coc/pskynet6/jzheng390/gavel`

Smoke mode:
```bash
/coc/pskynet6/jzheng390/miniconda3/envs/gavel-dev/bin/python \
interface_agents/summary_agent/controller/run_controller.py \
--mode smoke --request-id <request_id> --ticks 5 --tick-seconds 1
```

SLURM mode:
```bash
cat /path/to/request.json | \
/coc/pskynet6/jzheng390/miniconda3/envs/gavel-dev/bin/python \
interface_agents/summary_agent/controller/run_controller.py \
--mode slurm_summarize_agent --poll-seconds 2 --max-wait-seconds 21600
```

Important:
- Backend should not call `sbatch` directly in this mode.
- Controller submits `interface_agents/summary_agent/run_summary_agent_native.sbatch` internally.

Backend env recommendation:
- Set `INTERFACE_SUMMARY_AGENT_ENV_FILE=/coc/pskynet6/jzheng390/gavel/interface_agents/summary_agent/.env`
- Optional explicit checklist base for corpus lookup:
  - `INTERFACE_CHECKLIST_AGENT_BASE_DIR=/coc/pskynet6/jzheng390/gavel/interface_agents/checklist_agent`

## 2) Request JSON (stdin)

One JSON object.

Required fields:
- one case payload in `case` or `input_case` or single-entry `cases`
  - case must include `case_id`
  - case format should match checklist extraction input case format (inline full-text documents):
    - `case_documents_text` (required list)
    - `case_documents_title` (required list; same length as text)
    - `case_documents_doc_type` (required list; same length as text)
    - `case_documents_date` (optional list)
    - `case_documents_id` (optional list; int/string accepted, normalized to string)
  - extra fields on `case` are allowed and ignored by preprocessing unless used elsewhere
- `checklist` (object): extracted checklist map with evidence offsets
- `checklist_definitions` (object): `{ "Checklist_Item_Name": "Definition" }`

Optional fields:
- `request_id` (string)
- `model` (string, default `unsloth/gpt-oss-20b-BF16`)
- `max_steps` (integer >= 1, default `200`)
- `reasoning_effort` (`low|medium|high`, default `medium`)
- `summary_constraints` (array of strings)
- `focus_context` (optional non-empty string for scoped summary behavior/context)
- `k_recent_tool_outputs` (integer >= 1, default `5`)
- `resume` (bool, default `false`)
- `debug` (bool, default `false`)
- `prompt_config` (string path)
- `python_bin` (string; overrides preprocessing python)
- `slurm` object:
  - `partition` (default `nlprx-lab`)
  - `qos` (default `short`)

Checklist evidence contract:
- offsets are expected as:
  - `start_offset` (inclusive)
  - `end_offset` (exclusive)
  - zero-based indexing
- offset units are character offsets over raw `case_documents_text` strings (not bytes/tokens)
- Controller converts these offsets to sentence spans for runtime tools.

Checklist completeness guidance:
- Preferred/canonical: send all definition keys in `checklist` with empty `extracted: []` where needed.
- Accepted: partial checklist containing only filled bins.
- Runtime prompt builder will still show all definition keys and mark missing checklist bins as empty.

## 3) NDJSON Event Envelope

Each stdout line:
- `event_type`
- `request_id`
- `seq`
- `timestamp` (UTC ISO-8601)
- `data` (object)

For SLURM mode, envelope `request_id` equals generated controller `run_id`.

## 4) Event Types

Common:
- `started`
- `failed`
- `completed`

Smoke:
- `heartbeat`

SLURM summary-agent mode:
- `request_validated`
- `preprocess_started`
- `preprocess_completed`
- `document_map_ready`
- `checklist_prepared`
- `slurm_submitted`
- `slurm_state`
- `step_completed` (from ledger)

`completed` includes paths for:
- `result_payload_path`
- `manifest_path`
- `summary_path`
- `summary_state_path`

Completion artifact contract:
- Canonical final text source for backend ingestion: `summary_path` JSON (`summary` field).
- `result_payload.json` also mirrors that text in `summary`.
- No separate plain-text summary artifact is part of the backend contract.

## 5) Exit Codes

- `0`: successful terminal completion (`COMPLETED`)
- `1`: request validation/runtime exception
- `2`: smoke synthetic failure (`--fail-at`)
- `3`: controller timeout waiting for SLURM terminal state (`scancel` issued)
- `4`: SLURM terminal non-success state
- `130`: interrupted

## 6) Artifact Layout

Controller artifacts:
- `interface_agents/summary_agent/controller/runs/<run_id>/`

Key files:
- `events.ndjson`
- `request.json`
- `agent_request.json`
- `document_map.json`
- `summary.json`
- `result_payload.json`
- `manifest.json`

Agent output directory:
- `interface_agents/summary_agent/controller/runs/<run_id>/agent_output/<model>/<case_id>/summary_agent/`

Important files there:
- `summary_state.json`
- `ledger.jsonl`
- `stats.json`
- `run_<id>.json`

## 7) Example Request

```json
{
  "request_id": "summary_agent_backend_20260318_case46210",
  "case": {
    "case_id": "46210",
    "case_documents_text": ["..."],
    "case_documents_title": ["..."],
    "case_documents_doc_type": ["..."],
    "case_documents_date": ["..."],
    "case_documents_id": ["..."]
  },
  "checklist_definitions": {
    "Filing_Date": "The date the case was initially filed with the court",
    "Parties": "Who is involved in the case"
  },
  "checklist": {
    "Filing_Date": {
      "extracted": [
        {
          "value": "2025-02-12",
          "evidence": [
            {
              "source_document_id": "155313",
              "start_offset": 0,
              "end_offset": 18
            }
          ]
        }
      ]
    }
  },
  "model": "unsloth/gpt-oss-20b-BF16",
  "max_steps": 200,
  "reasoning_effort": "medium",
  "focus_context": "Summarize this as the ECF procedural posture narrative for the primary case timeline only.",
  "summary_constraints": [
    "Write plain narrative paragraphs only.",
    "Avoid bullet lists and markdown headings."
  ],
  "slurm": {
    "partition": "nlprx-lab",
    "qos": "short"
  }
}
```

## 8) Prompt Location and Injection Strategy

Prompt source files:
- Developer/system prompt YAML:
  - `interface_agents/summary_agent/native/prompts_gpt_oss_summary_native.yaml`
  - key: `developer_prompt`
- Turn snapshot formatter (user message template builder):
  - `interface_agents/summary_agent/runtime/snapshot_formatter.py`
- Runtime prompt assembly:
  - `interface_agents/summary_agent/native/driver_native.py`
  - methods: `_load_developer_prompt`, `_build_snapshot`, `_build_messages`

Prompt override knobs:
- Request field `prompt_config` (optional path) -> exported as `PROMPT_CONFIG` to sbatch.
- If omitted, runtime default is:
  - `native/prompts_gpt_oss_summary_native.yaml`

Injection flow (per run):
1. Backend sends `checklist` (offset evidence) + `checklist_definitions` + `case`.
2. Controller preprocesses case docs into sentence-indexed corpus.
3. Controller converts checklist offsets to sentence spans (overfetch rule), writes:
   - `controller/runs/<run_id>/agent_request.json`
4. Native runtime loads that `agent_request.json` and injects:
   - `checklist` (sentence-span grounded values)
   - `checklist_definitions`
   - `summary_constraints` (if provided)
   - `focus_context` (if provided)

Injection flow (per turn):
1. `developer` message = YAML `developer_prompt`.
2. Prior tool-call history is injected:
   - full args/results for most recent `k_recent_tool_outputs` turns
   - summarized signatures for older turns
3. `user` message = snapshot formatter output containing:
   - objective and run metadata
   - optional focus context guidance (`focus_context`)
   - full checklist definitions and current extracted values/evidence
   - current summary draft paragraphs (`summary_state`)
   - document inventory and coverage/read status (after `list_documents`)
   - recent actions + last tool result
   - stop-review state + next-action instruction

Summary text style controls:
- Developer prompt hard rules in YAML.
- Snapshot “summary constraints” section from request (`summary_constraints`).
- Snapshot “Focus Context” section when provided (`focus_context`).
- Tool contract itself enforces paragraph-edit workflow (`append/update/delete/get_summary_state`) and no final free-text outside tools.

## 9) Latest Manual Run Evaluation (2026-03-19 UTC)

Run metadata:
- `run_id`: `run_20260319T025055Z_6dcb90725b`
- `request_id`: `summary_agent_manual_46110_20260319T024154Z`
- `job_id`: `2576901`
- controller terminal event: `completed`
- SLURM terminal state: `COMPLETED`

Outcome:
- Summary generation succeeded.
- Final summary stats: `paragraph_count=1`, `character_count=1572`, `non_empty=true`
- Agent steps: `55`
- Total tokens: `691196`
- Wall-clock duration (controller event stream): about `952.6s` (`15m 52.6s`)

Canonical summary artifacts:
- `summary_path` (backend canonical):  
  `/coc/pskynet6/jzheng390/gavel/interface_agents/summary_agent/controller/runs/run_20260319T025055Z_6dcb90725b/summary.json`
- `result_payload_path`:  
  `/coc/pskynet6/jzheng390/gavel/interface_agents/summary_agent/controller/runs/run_20260319T025055Z_6dcb90725b/result_payload.json`
- `manifest_path`:  
  `/coc/pskynet6/jzheng390/gavel/interface_agents/summary_agent/controller/runs/run_20260319T025055Z_6dcb90725b/manifest.json`

Reasoning/trace artifacts:
- per-turn tool execution ledger (`tool`, args/result summaries):  
  `/coc/pskynet6/jzheng390/gavel/interface_agents/summary_agent/controller/runs/run_20260319T025055Z_6dcb90725b/agent_output/gpt-oss-20b-BF16/46110/summary_agent/ledger.jsonl`
- per-turn raw model responses (includes model analysis traces + tool call payloads):  
  `/coc/pskynet6/jzheng390/gavel/interface_agents/summary_agent/controller/runs/run_20260319T025055Z_6dcb90725b/agent_output/gpt-oss-20b-BF16/46110/summary_agent/raw_responses.jsonl`
- token accounting by step:  
  `/coc/pskynet6/jzheng390/gavel/interface_agents/summary_agent/controller/runs/run_20260319T025055Z_6dcb90725b/agent_output/gpt-oss-20b-BF16/46110/summary_agent/stats.json`
- controller control-plane event stream:  
  `/coc/pskynet6/jzheng390/gavel/interface_agents/summary_agent/controller/runs/run_20260319T025055Z_6dcb90725b/events.ndjson`
- runtime logs:  
  `/coc/pskynet6/jzheng390/gavel/interface_agents/summary_agent/agent_logs/gpt-oss-20b-BF16/46110/46110_summary_agent_steps200.log`  
  `/coc/pskynet6/jzheng390/gavel/interface_agents/summary_agent/agent_logs/summary_agent_native_run-2576901.out`

## 10) Backend Rewire + Test Plan

Suggested backend constants:

```python
# BEFORE
SUMMARY_CONTROLLER = "/coc/pskynet6/jzheng390/gavel/src/summarize_documents/summary_agent/controller/run_controller.py"
SUMMARY_RUNS_ROOT = "/coc/pskynet6/jzheng390/gavel/src/summarize_documents/summary_agent/controller/runs"

# AFTER
SUMMARY_CONTROLLER = "/coc/pskynet6/jzheng390/gavel/interface_agents/summary_agent/controller/run_controller.py"
SUMMARY_RUNS_ROOT = "/coc/pskynet6/jzheng390/gavel/interface_agents/summary_agent/controller/runs"
```

Smoke test (control-plane only):
```bash
/coc/pskynet6/jzheng390/miniconda3/envs/gavel-dev/bin/python \
/coc/pskynet6/jzheng390/gavel/interface_agents/summary_agent/controller/run_controller.py \
--mode smoke --request-id backend_summary_migration_smoke --ticks 2 --tick-seconds 1
```

End-to-end test (SLURM):
```bash
cat /path/to/summary_request.json | \
/coc/pskynet6/jzheng390/miniconda3/envs/gavel-dev/bin/python \
/coc/pskynet6/jzheng390/gavel/interface_agents/summary_agent/controller/run_controller.py \
--mode slurm_summarize_agent --poll-seconds 2 --max-wait-seconds 21600
```

Acceptance checks:
1. NDJSON emits `started`, `request_validated`, `slurm_submitted`, and terminal `completed`.
2. `completed.data.run_dir` is under `.../interface_agents/summary_agent/controller/runs/<run_id>/`.
3. `completed.data.summary_path` exists and includes `summary`.
4. `completed.data.result_payload_path` exists and mirrors `summary`.
