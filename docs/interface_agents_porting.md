# Interface Agents Porting Notes

This repository carries the source of truth for the remote agent runtimes in `interface_agents/`.

The backend no longer assumes a persistent remote checkout of this repository.

## Runtime Model
- One-time setup on the head node provides:
  - a persistent Python interpreter
  - shared model/cache directories
  - a writable staged-run root
- For each backend run, the backend creates:
  - `<remote-stage-root>/<backend-run-id>/`
- The backend rsyncs the local `interface_agents/` tree into that directory.
- The backend writes stage-local `.env` files into:
  - `interface_agents/checklist_agent/.env`
  - `interface_agents/summary_agent/.env`
- Extraction and summary both execute from that staged snapshot.

## Import Scope
When copying `interface_agents/` into this repository, bring over source and checked-in config only. Do not import runtime state, generated artifacts, or secrets.

Keep:
- `interface_agents/checklist_agent/agent/`
- `interface_agents/checklist_agent/config/`
- `interface_agents/checklist_agent/controller/*.py`
- `interface_agents/checklist_agent/native/`
- `interface_agents/checklist_agent/state/`
- `interface_agents/checklist_agent/*.py`
- `interface_agents/checklist_agent/*.sbatch`
- `interface_agents/checklist_agent/README.md`
- `interface_agents/checklist_agent/.env.example`
- `interface_agents/summary_agent/controller/*.py`
- `interface_agents/summary_agent/native/`
- `interface_agents/summary_agent/runtime/`
- `interface_agents/summary_agent/*.py`
- `interface_agents/summary_agent/*.sbatch`
- `interface_agents/summary_agent/README.md`
- `interface_agents/summary_agent/.env.example`
- `interface_agents/requirements.txt`

Exclude:
- `interface_agents/**/.env`
- `interface_agents/**/agent_logs/`
- `interface_agents/**/data/`
- `interface_agents/**/controller/runs/`
- `interface_agents/**/controller/requests/`
- `interface_agents/**/__pycache__/`

## Suggested Import Command
Run from this repository root:

```bash
rsync -az \
  --exclude='.env' \
  --exclude='agent_logs/' \
  --exclude='data/' \
  --exclude='controller/runs/' \
  --exclude='controller/requests/' \
  --exclude='__pycache__/' \
  sky1:/coc/pskynet6/jzheng390/gavel/interface_agents/ \
  ./interface_agents/
```

## One-Time Bootstrap on the Head Node
To install dependencies into the persistent remote environment, sync `interface_agents/` once to a bootstrap directory and install from the shared requirements file:

```bash
rsync -az \
  --exclude='.env' \
  --exclude='agent_logs/' \
  --exclude='data/' \
  --exclude='controller/runs/' \
  --exclude='controller/requests/' \
  --exclude='__pycache__/' \
  ./interface_agents/ \
  sky1:/coc/pskynet6/$USER/flash/bootstrap/interface_agents/

ssh sky1 \
  '"/coc/pskynet6/$USER/flash/miniconda3/envs/gavel-dev/bin/python" -m pip install -r \
  "/coc/pskynet6/$USER/flash/bootstrap/interface_agents/requirements.txt"'
```

## After Import
1. The backend stages `interface_agents/` automatically for each run.
2. The head node does not need a persistent application checkout.
3. Runtime cleanup is manual; staged run directories are intentionally left in place for inspection.
