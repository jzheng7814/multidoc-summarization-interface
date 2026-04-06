#!/usr/bin/env python3
"""Native controller wrapper.

Reuses run_controller.py behavior but routes SLURM submission to
run_agent_native.sbatch (GPT-OSS native tool-calling runtime).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure sibling module imports resolve when executed as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_controller as _base

_base.SBATCH_SCRIPT = _base.BASE_DIR / "run_agent_native.sbatch"


def main() -> int:
    return _base.main()


if __name__ == "__main__":
    raise SystemExit(main())
