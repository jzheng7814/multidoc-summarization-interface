#!/usr/bin/env python3
"""Entry point for native checklist-grounded summary generation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parent))

from native.driver_native import NativeSummaryDriver


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run native GPT-OSS tool-calling summary generation",
    )
    parser.add_argument("corpus_path", help="Path to the processed document corpus for one case")
    parser.add_argument(
        "--request-json",
        required=True,
        help="Path to summary-agent request payload containing checklist + checklist_definitions",
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
        help="GPT-OSS reasoning effort level",
    )
    parser.add_argument(
        "--summary-state-path",
        default="summary_state.json",
        help="Path for paragraph-state persistence/output",
    )
    parser.add_argument(
        "--ledger-path",
        default="ledger.jsonl",
        help="Path for ledger persistence/output",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional fixed run ID (auto-generated when omitted)",
    )
    parser.add_argument("--resume", action="store_true", help="Resume from existing artifacts")
    parser.add_argument("--quiet", action="store_true", help="Reduce output verbosity")
    parser.add_argument("--debug", action="store_true", help="Debug mode with extra output")
    parser.add_argument(
        "--recent-actions",
        type=int,
        default=8,
        help="Recent actions to keep in snapshot history",
    )
    parser.add_argument(
        "--k-recent-tool-outputs",
        type=int,
        default=5,
        help="Keep full tool outputs for the most recent K turns; summarize older turns",
    )
    parser.add_argument(
        "--prompt-config",
        default=None,
        help="Optional prompt YAML override",
    )
    return parser.parse_args()


def load_request_payload(path: str) -> Dict[str, Any]:
    request_path = Path(path)
    if not request_path.exists():
        raise FileNotFoundError(f"Request JSON not found: {request_path}")

    with request_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    if not isinstance(payload, dict):
        raise ValueError("request JSON must be an object")
    if not isinstance(payload.get("checklist"), dict):
        raise ValueError("request JSON must include object field `checklist`")
    if not isinstance(payload.get("checklist_definitions"), dict):
        raise ValueError("request JSON must include object field `checklist_definitions`")

    return payload


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

    request_payload = load_request_payload(args.request_json)

    print("Summary Agent Native Runtime")
    print(f"Model: {model}")
    print(f"Corpus: {args.corpus_path}")
    print(f"Request: {args.request_json}")
    print("=" * 60)

    driver = NativeSummaryDriver(
        corpus_path=args.corpus_path,
        request_payload=request_payload,
        summary_state_path=args.summary_state_path,
        ledger_path=args.ledger_path,
        model_name=model,
        max_steps=args.max_steps,
        reasoning_effort=args.reasoning_effort,
        verbose=verbose,
        recent_actions=args.recent_actions,
        k_recent_tool_outputs=args.k_recent_tool_outputs,
        prompt_config_path=args.prompt_config,
    )

    results = driver.run(run_id=args.run_id, resume=args.resume)
    stats = results.get("summary_stats") or {}
    print(f"Paragraphs: {stats.get('paragraph_count', 0)}")
    print(f"Characters: {stats.get('character_count', 0)}")
    print(f"Total Steps: {results.get('total_steps', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
