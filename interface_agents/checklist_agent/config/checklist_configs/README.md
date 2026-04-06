# Checklist Configurations

This folder stores reusable checklist definitions for direct agent runs.

## Important Contract Note

There are now two ways checklist definitions are provided:

1. **Controller runs (`run_controller.py` / `run_controller_native.py`)**
   - Request payloads must send inline `checklist_spec`.
   - Path-based `checklist_config` in request JSON is rejected.
   - The controller writes run-local generated files under:
     - `controller/runs/<run_id>/generated_checklists/`

2. **Direct agent runs (`run_agent.py` / `native/run_agent_native.py`)**
   - You still pass `--checklist-config` paths from this directory.

## Directory Structure

```text
checklist_configs/
├── all/
│   └── all_26_items.yaml
├── grouped/
│   ├── 01_basic_case_info.yaml
│   ├── 02_legal_foundation.yaml
│   ├── 03_judge_info.yaml
│   ├── 04_related_cases.yaml
│   ├── 05_filings_proceedings.yaml
│   ├── 06_decrees.yaml
│   ├── 07_settlements.yaml
│   ├── 08_monitoring.yaml
│   └── 09_context.yaml
├── individual/
│   ├── 01_filing_date.yaml
│   ├── 02_parties.yaml
│   ├── ...
│   └── 26_factual_basis.yaml
```

## Direct Run Usage (Path-Based)

From `interface_agents/checklist_agent/`:

```bash
# Custom scaffold, all items
python run_agent.py data/20_human_eval_cases/45696 \
  --checklist-config config/checklist_configs/all/all_26_items.yaml

# Custom scaffold, one item
python run_agent.py data/20_human_eval_cases/45696 \
  --checklist-config config/checklist_configs/individual/08_judge_name.yaml

# Native scaffold, one grouped config
python native/run_agent_native.py data/20_human_eval_cases/45696 \
  --checklist-config config/checklist_configs/grouped/01_basic_case_info.yaml \
  --model unsloth/gpt-oss-20b-BF16
```

## Mapping to Inline `checklist_spec`

Controller request payloads must provide equivalent content inline:

- **`checklist_strategy: "all"`**
  - global `checklist_spec.user_instruction`
  - global `checklist_spec.constraints`
  - `checklist_spec.checklist_items[]` with `key`, `description`

- **`checklist_strategy: "individual"`**
  - per item: `key`, `description`, `user_instruction`, `constraints`
  - plus per-item runtime tuning: `max_steps`, `reasoning_effort`

Validation behavior is enforced directly in `controller/run_controller.py`.

## Output Layout (Direct Agent Runs)

```text
output/{model_suffix}/{case_id}/{category}/{config_name}/
├── checklist.json
├── ledger.jsonl
└── stats.json
```

`category` is inferred from path (`all`, `grouped`, `individual`, or `custom`).
