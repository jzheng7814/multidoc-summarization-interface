#!/usr/bin/env python3
"""Entry point for GPT-OSS native tool-calling extraction."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add gavel_agent root to import path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from native.driver_native import NativeDriver


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run native GPT-OSS tool-calling checklist extraction"
    )
    parser.add_argument(
        "corpus_path",
        help="Path to the processed document corpus for one case",
    )
    parser.add_argument(
        "--model",
        default="unsloth/gpt-oss-20b-BF16",
        help="Model name (GPT-OSS variants only)",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=200,
        help="Maximum native agent steps before forced stop",
    )
    parser.add_argument(
        "--reasoning-effort",
        choices=["low", "medium", "high"],
        default="medium",
        help="GPT-OSS reasoning effort level (default: medium)",
    )
    parser.add_argument(
        "--store-path",
        default="checklist_store.json",
        help="Path for checklist persistence/output",
    )
    parser.add_argument(
        "--ledger-path",
        default="ledger.jsonl",
        help="Path for ledger persistence/output",
    )
    parser.add_argument(
        "--config-dir",
        default="config",
        help="Directory containing config files",
    )
    parser.add_argument(
        "--checklist-config",
        default="config/checklist_configs/all/all_26_items.yaml",
        help="Path to generated checklist config for this run",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from existing checklist/ledger/stats artifacts",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Reduce output verbosity",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Debug mode with extra output",
    )
    parser.add_argument(
        "--recent-actions",
        type=int,
        default=5,
        help="Recent actions to keep in detailed snapshot history",
    )
    parser.add_argument(
        "--k-recent-tool-outputs",
        type=int,
        default=5,
        help="Keep full tool outputs for the most recent K turns; summarize older turns",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    model = str(args.model)
    if "gpt-oss" not in model.lower():
        raise ValueError("native runtime currently supports GPT-OSS models only")

    if args.quiet:
        verbose = 0
    elif args.debug:
        verbose = 2
    else:
        verbose = 1

    print("Legal Agent Native Runtime")
    print(f"Model: {model}")
    print(f"Corpus: {args.corpus_path}")
    print("=" * 60)

    driver = NativeDriver(
        corpus_path=args.corpus_path,
        store_path=args.store_path,
        ledger_path=args.ledger_path,
        config_dir=args.config_dir,
        checklist_config_path=args.checklist_config,
        model_name=model,
        max_steps=args.max_steps,
        reasoning_effort=args.reasoning_effort,
        verbose=verbose,
        recent_actions=args.recent_actions,
        k_recent_tool_outputs=args.k_recent_tool_outputs,
    )
    results = driver.run(resume=args.resume)
    stats = results["completion_stats"]
    total = stats.get("total", stats.get("filled", 0) + stats.get("empty", 0))
    print(f"Filled: {stats.get('filled', 0)}/{total}")
    print(f"Empty: {stats.get('empty', 0)}")
    print(f"Total Steps: {results.get('total_steps', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
