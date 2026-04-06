#!/usr/bin/env python3
"""SSH-stream controller for smoke and SLURM checklist extraction flows."""

from __future__ import annotations

import argparse
import json
import os
import uuid
import re
import shutil
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


def load_dotenv_file(path: Path) -> None:
    """Load KEY=VALUE lines from a dotenv file into process env (non-destructive)."""
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export ") :].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not key:
                continue
            value = value.strip()
            if value and ((value[0] == value[-1]) and value[0] in {'"', "'"}):
                value = value[1:-1]
            os.environ.setdefault(key, value)


DEFAULT_BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_ENV_PATH = DEFAULT_BASE_DIR / ".env"
load_dotenv_file(Path(os.environ.get("INTERFACE_AGENT_ENV_FILE", str(DEFAULT_ENV_PATH))))

BASE_DIR = Path(os.environ.get("INTERFACE_AGENT_BASE_DIR", str(DEFAULT_BASE_DIR))).expanduser().resolve()
PYTHON_BIN = os.environ.get("INTERFACE_AGENT_PYTHON_BIN", sys.executable)
SBATCH_SCRIPT = Path(
    os.environ.get("INTERFACE_AGENT_SBATCH_SCRIPT", str(BASE_DIR / "run_agent.sbatch"))
).expanduser()
RUNS_BASE = Path(
    os.environ.get("INTERFACE_AGENT_RUNS_BASE", str(BASE_DIR / "controller" / "runs"))
).expanduser()
SLURM_BIN_DIR = Path(
    os.environ.get("INTERFACE_AGENT_SLURM_BIN_DIR", "/opt/slurm/Ubuntu-20.04/current/bin")
).expanduser()
TERMINAL_STATES = {
    "COMPLETED",
    "FAILED",
    "CANCELLED",
    "TIMEOUT",
    "OUT_OF_MEMORY",
    "NODE_FAIL",
    "PREEMPTED",
    "BOOT_FAIL",
    "DEADLINE",
}
ALLOWED_REASONING_EFFORTS = {"low", "medium", "high"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def slurm_executable(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    return str(SLURM_BIN_DIR / name)


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


class Emitter:
    """Maintains sequence numbers for NDJSON events."""

    def __init__(self, request_id: str, mirror_path: Optional[Path] = None):
        self.request_id = request_id
        self.seq = 0
        self._mirror = None
        if mirror_path is not None:
            mirror_path.parent.mkdir(parents=True, exist_ok=True)
            self._mirror = mirror_path.open("a", encoding="utf-8")

    def emit(self, event_type: str, **data: Any) -> None:
        self.seq += 1
        payload: Dict[str, Any] = {
            "event_type": event_type,
            "request_id": self.request_id,
            "seq": self.seq,
            "timestamp": utc_now_iso(),
            "data": data,
        }
        line = json.dumps(payload, ensure_ascii=True) + "\n"
        sys.stdout.write(line)
        sys.stdout.flush()
        if self._mirror is not None:
            self._mirror.write(line)
            self._mirror.flush()

    def close(self) -> None:
        if self._mirror is not None:
            self._mirror.close()
            self._mirror = None


def parse_json_or_string(raw: Optional[str]) -> Optional[Any]:
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def run_cmd(cmd: List[str], cwd: Optional[Path] = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        check=False,
    )


def normalize_slurm_state(raw_state: str) -> str:
    """Normalize SLURM state strings to canonical tokens."""
    state = (raw_state or "").strip()
    if not state:
        return "UNKNOWN"

    state = state.split("|", 1)[0].strip()
    if state.endswith("+"):
        state = state[:-1].strip()

    match = re.match(r"^([A-Za-z_]+)", state)
    if not match:
        return "UNKNOWN"
    return match.group(1).upper()


def slurm_state(job_id: str) -> str:
    squeue = run_cmd([slurm_executable("squeue"), "-h", "-j", job_id, "-o", "%T"])
    state = (squeue.stdout or "").strip().splitlines()
    if state:
        return normalize_slurm_state(state[0])

    sacct = run_cmd([slurm_executable("sacct"), "-j", job_id, "-n", "-P", "-o", "State"])
    for line in (sacct.stdout or "").splitlines():
        token = normalize_slurm_state(line)
        if token and token != "UNKNOWN":
            return token
    return "UNKNOWN"


def bool_to_str(value: bool) -> str:
    return "true" if value else "false"


def parse_stdin_json() -> Dict[str, Any]:
    raw = sys.stdin.read().strip()
    if not raw:
        raise ValueError("Expected JSON request on stdin, got empty input")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Request JSON must be an object")
    return data


def validate_run_id(run_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", run_id):
        raise ValueError(
            "run_id must match ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ to prevent unsafe paths"
        )
    return run_id


def generate_run_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"run_{ts}_{uuid.uuid4().hex[:10]}"


def normalize_input_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    raw_input = payload.get("input")
    if not isinstance(raw_input, dict):
        raise ValueError("Request must provide one input object in `input`.")

    corpus_id = require_non_empty_string(raw_input.get("corpus_id"), "input.corpus_id")
    raw_documents = raw_input.get("documents")
    if not isinstance(raw_documents, list) or not raw_documents:
        raise ValueError("`input.documents` is required and must contain at least one document.")

    documents: List[Dict[str, Any]] = []
    for idx, raw_document in enumerate(raw_documents):
        path = f"input.documents[{idx}]"
        if not isinstance(raw_document, dict):
            raise ValueError(f"`{path}` must be an object")
        documents.append(
            {
                "document_id": require_non_empty_string(raw_document.get("document_id"), f"{path}.document_id"),
                "title": require_non_empty_string(raw_document.get("title"), f"{path}.title"),
                "doc_type": str(raw_document.get("doc_type") or "").strip(),
                "date": str(raw_document.get("date") or "").strip() or None,
                "text": require_non_empty_string(raw_document.get("text"), f"{path}.text"),
            }
        )

    return {
        "corpus_id": corpus_id,
        "documents": documents,
    }


def parse_checklist_strategy(request: Dict[str, Any]) -> str:
    raw_strategy = request.get("checklist_strategy")
    strategy = str(raw_strategy or "").strip().lower()
    if strategy not in {"all", "individual"}:
        raise ValueError("`checklist_strategy` must be explicitly set to 'all' or 'individual'")
    return strategy


def require_non_empty_string(value: Any, field_path: str) -> str:
    if value is None:
        raise ValueError(f"`{field_path}` is required")
    if not isinstance(value, str):
        raise ValueError(f"`{field_path}` must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"`{field_path}` must not be empty")
    return normalized


def require_constraints_list(value: Any, field_path: str) -> List[str]:
    if value is None:
        raise ValueError(f"`{field_path}` is required (empty list is allowed, null is not)")
    if not isinstance(value, list):
        raise ValueError(f"`{field_path}` must be a list")
    normalized: List[str] = []
    for idx, entry in enumerate(value):
        if not isinstance(entry, str):
            raise ValueError(f"`{field_path}[{idx}]` must be a string")
        cleaned = entry.strip()
        if not cleaned:
            raise ValueError(f"`{field_path}[{idx}]` must not be empty")
        normalized.append(cleaned)
    return normalized


def require_positive_int(value: Any, field_path: str) -> int:
    if value is None:
        raise ValueError(f"`{field_path}` is required")
    if isinstance(value, bool):
        raise ValueError(f"`{field_path}` must be an integer >= 1")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"`{field_path}` must be an integer >= 1") from exc
    if parsed < 1:
        raise ValueError(f"`{field_path}` must be >= 1")
    return parsed


def require_reasoning_effort(value: Any, field_path: str) -> str:
    if value is None:
        raise ValueError(f"`{field_path}` is required")
    if not isinstance(value, str):
        raise ValueError(f"`{field_path}` must be a string")
    normalized = value.strip().lower()
    if normalized not in ALLOWED_REASONING_EFFORTS:
        allowed = ", ".join(sorted(ALLOWED_REASONING_EFFORTS))
        raise ValueError(f"`{field_path}` must be one of: {allowed}")
    return normalized


def parse_optional_focus_context(value: Any, field_path: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"`{field_path}` must be a string when provided")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"`{field_path}` must not be empty when provided")
    return normalized


def parse_checklist_items(spec: Dict[str, Any], strategy: str) -> List[Dict[str, Any]]:
    raw_items = spec.get("checklist_items")
    if raw_items is None:
        raise ValueError("`checklist_spec.checklist_items` is required")
    if not isinstance(raw_items, list):
        raise ValueError("`checklist_spec.checklist_items` must be an ordered array")
    if not raw_items:
        raise ValueError("`checklist_spec.checklist_items` must contain at least one item")

    seen_keys: Set[str] = set()
    parsed_items: List[Dict[str, Any]] = []
    for idx, raw_item in enumerate(raw_items):
        item_path = f"checklist_spec.checklist_items[{idx}]"
        if not isinstance(raw_item, dict):
            raise ValueError(f"`{item_path}` must be an object")

        key = require_non_empty_string(raw_item.get("key"), f"{item_path}.key")
        if key in seen_keys:
            raise ValueError(f"Duplicate checklist key in spec: `{key}`")
        seen_keys.add(key)

        description = require_non_empty_string(raw_item.get("description"), f"{item_path}.description")
        parsed_item: Dict[str, Any] = {
            "key": key,
            "description": description,
        }

        if strategy == "all":
            if "user_instruction" in raw_item:
                raise ValueError(
                    f"`{item_path}.user_instruction` is not allowed when checklist_strategy='all'; "
                    "use global `checklist_spec.user_instruction`"
                )
            if "constraints" in raw_item:
                raise ValueError(
                    f"`{item_path}.constraints` is not allowed when checklist_strategy='all'; "
                    "use global `checklist_spec.constraints`"
                )
            if "max_steps" in raw_item:
                raise ValueError(
                    f"`{item_path}.max_steps` is not allowed when checklist_strategy='all'; "
                    "use top-level `max_steps`"
                )
            if "reasoning_effort" in raw_item:
                raise ValueError(
                    f"`{item_path}.reasoning_effort` is not allowed when checklist_strategy='all'; "
                    "use top-level `reasoning_effort`"
                )
        else:
            parsed_item["user_instruction"] = require_non_empty_string(
                raw_item.get("user_instruction"),
                f"{item_path}.user_instruction",
            )
            parsed_item["constraints"] = require_constraints_list(
                raw_item.get("constraints"),
                f"{item_path}.constraints",
            )
            parsed_item["max_steps"] = require_positive_int(
                raw_item.get("max_steps"),
                f"{item_path}.max_steps",
            )
            parsed_item["reasoning_effort"] = require_reasoning_effort(
                raw_item.get("reasoning_effort"),
                f"{item_path}.reasoning_effort",
            )

        parsed_items.append(parsed_item)

    return parsed_items


def parse_checklist_spec(request: Dict[str, Any], strategy: str) -> Dict[str, Any]:
    if "checklist_config" in request:
        raise ValueError(
            "`checklist_config` path-based input is no longer supported. "
            "Provide inline `checklist_spec` instead."
        )

    raw_spec = request.get("checklist_spec")
    if not isinstance(raw_spec, dict):
        raise ValueError("`checklist_spec` is required and must be an object")

    items = parse_checklist_items(raw_spec, strategy=strategy)

    if strategy == "all":
        return {
            "strategy": strategy,
            "user_instruction": require_non_empty_string(
                raw_spec.get("user_instruction"),
                "checklist_spec.user_instruction",
            ),
            "constraints": require_constraints_list(
                raw_spec.get("constraints"),
                "checklist_spec.constraints",
            ),
            "items": items,
        }

    if "user_instruction" in raw_spec:
        raise ValueError(
            "`checklist_spec.user_instruction` is not allowed when checklist_strategy='individual'; "
            "provide per-item `user_instruction`"
        )
    if "constraints" in raw_spec:
        raise ValueError(
            "`checklist_spec.constraints` is not allowed when checklist_strategy='individual'; "
            "provide per-item `constraints`"
        )

    return {
        "strategy": strategy,
        "items": items,
    }


def slugify_key(key: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", key).strip("_").lower()
    return slug or "item"


def write_generated_checklist_config(
    path: Path,
    user_instruction: str,
    constraints: List[str],
    items: List[Dict[str, Any]],
    focus_context: Optional[str] = None,
) -> None:
    checklist_items: Dict[str, Dict[str, str]] = {}
    for item in items:
        checklist_items[item["key"]] = {"description": item["description"]}

    config_payload = {
        "user_instruction": user_instruction,
        "constraints": constraints,
        "checklist_items": checklist_items,
    }
    if focus_context is not None:
        config_payload["focus_context"] = focus_context
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(config_payload, f, ensure_ascii=False, indent=2)


def materialize_checklist_configs(
    run_dir: Path,
    spec: Dict[str, Any],
    focus_context: Optional[str] = None,
) -> List[str]:
    strategy = spec["strategy"]
    items: List[Dict[str, Any]] = spec["items"]
    base_dir = run_dir / "generated_checklists" / strategy

    if strategy == "all":
        config_path = base_dir / "all_items.yaml"
        write_generated_checklist_config(
            config_path,
            user_instruction=spec["user_instruction"],
            constraints=spec["constraints"],
            items=items,
            focus_context=focus_context,
        )
        return [str(config_path)]

    config_paths: List[str] = []
    for idx, item in enumerate(items, start=1):
        config_path = base_dir / f"{idx:03d}_{slugify_key(item['key'])}.yaml"
        write_generated_checklist_config(
            config_path,
            user_instruction=item["user_instruction"],
            constraints=item["constraints"],
            items=[item],
            focus_context=focus_context,
        )
        config_paths.append(str(config_path))
    return config_paths


def config_category(checklist_config: str) -> str:
    if "/all/" in checklist_config:
        return "all"
    if "/grouped/" in checklist_config:
        return "grouped"
    if "/individual/" in checklist_config:
        return "individual"
    return "custom"


@dataclass
class Paths:
    run_dir: Path
    events_path: Path
    request_path: Path
    input_json: Path
    data_dataset_name: str
    output_dir: Path
    ledger_path: Path
    agent_checklist_path: Path
    final_checklist_path: Path
    stats_path: Path
    agent_log_path: Path
    slurm_log_path: Optional[Path]
    document_map_path: Path
    checklist_ndjson_path: Path
    result_payload_path: Path
    manifest_path: Path


def build_paths(
    run_id: str,
    corpus_id: str,
    model_name: str,
    checklist_config: str,
    max_steps: int,
    resume: bool,
    job_id: Optional[str] = None,
) -> Paths:
    run_dir = RUNS_BASE / run_id
    model_suffix = model_name.split("/")[-1]
    config_suffix = Path(checklist_config).stem
    category = config_category(checklist_config)

    output_base_dir = f"controller/runs/{run_id}/agent_output"
    output_dir = BASE_DIR / output_base_dir / model_suffix / corpus_id / category / config_suffix
    ledger_path = output_dir / "ledger.jsonl"
    agent_checklist_path = output_dir / "checklist.json"
    stats_path = output_dir / "stats.json"

    log_name = f"{corpus_id}_{category}_{config_suffix}_steps{max_steps}"
    if resume:
        log_name += "_resume"
    agent_log_path = BASE_DIR / "agent_logs" / model_suffix / corpus_id / f"{log_name}.log"

    slurm_log_path = None
    if job_id:
        slurm_log_path = BASE_DIR / "agent_logs" / f"checklist_agent_native_run-{job_id}.out"

    return Paths(
        run_dir=run_dir,
        events_path=run_dir / "events.ndjson",
        request_path=run_dir / "request.json",
        input_json=run_dir / f"controller_{run_id}.json",
        data_dataset_name=f"controller_{run_id}",
        output_dir=output_dir,
        ledger_path=ledger_path,
        agent_checklist_path=agent_checklist_path,
        final_checklist_path=run_dir / "checklist.json",
        stats_path=stats_path,
        agent_log_path=agent_log_path,
        slurm_log_path=slurm_log_path,
        document_map_path=run_dir / "document_map.json",
        checklist_ndjson_path=run_dir / "checklist.ndjson",
        result_payload_path=run_dir / "result_payload.json",
        manifest_path=run_dir / "manifest.json",
    )


def emit_new_steps(
    emitter: Emitter,
    ledger_path: Path,
    read_pos: int,
    seen_steps: Set[int],
    file_identity: Optional[Tuple[int, int]],
    extra_fields: Optional[Dict[str, Any]] = None,
) -> Tuple[int, Optional[Tuple[int, int]]]:
    if not ledger_path.exists():
        return read_pos, file_identity

    stat = ledger_path.stat()
    current_identity = (stat.st_dev, stat.st_ino)
    file_size = stat.st_size

    if file_identity is not None and current_identity != file_identity:
        read_pos = 0

    if read_pos > file_size:
        read_pos = 0

    with ledger_path.open("r", encoding="utf-8") as f:
        f.seek(read_pos)
        lines = f.readlines()
        read_pos = f.tell()

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        event = record.get("event", {})
        step = event.get("step")
        if isinstance(step, int) and step not in seen_steps:
            seen_steps.add(step)
            payload = {
                "step": step,
                "tool_name": event.get("tool_name"),
                "success": event.get("success"),
            }
            if extra_fields:
                payload.update(extra_fields)
            emitter.emit("step_completed", **payload)
    return read_pos, current_identity


def run_smoke(args: argparse.Namespace) -> int:
    if not args.request_id:
        raise ValueError("--request-id is required in smoke mode")
    if args.ticks < 0:
        raise ValueError("--ticks must be >= 0")
    if args.tick_seconds < 0:
        raise ValueError("--tick-seconds must be >= 0")
    if args.fail_at == 0:
        raise ValueError("--fail-at must be -1 or a 1-based heartbeat index")

    emitter = Emitter(args.request_id)
    start = time.monotonic()
    emitter.emit(
        "started",
        mode="smoke",
        ticks=args.ticks,
        tick_seconds=args.tick_seconds,
        fail_at=args.fail_at,
        payload=parse_json_or_string(args.payload),
        pid=os.getpid(),
    )

    for i in range(1, args.ticks + 1):
        time.sleep(args.tick_seconds)
        emitter.emit(
            "heartbeat",
            tick=i,
            ticks_total=args.ticks,
            progress=(i / args.ticks) if args.ticks else 1.0,
        )
        if args.fail_at > 0 and i == args.fail_at:
            emitter.emit(
                "failed",
                mode="smoke",
                error="Synthetic failure requested by --fail-at",
                fail_at=args.fail_at,
                elapsed_seconds=round(time.monotonic() - start, 3),
            )
            return 2

    emitter.emit(
        "completed",
        mode="smoke",
        ticks_emitted=args.ticks,
        elapsed_seconds=round(time.monotonic() - start, 3),
        exit_code=0,
    )
    emitter.close()
    return 0


def run_preprocess(
    emitter: Emitter,
    input_payload: Dict[str, Any],
    model_name: str,
    paths: Paths,
) -> Tuple[str, Path]:
    corpus_id = str(input_payload["corpus_id"])
    with paths.input_json.open("w", encoding="utf-8") as f:
        json.dump([input_payload], f, ensure_ascii=False)

    emitter.emit("preprocess_started", corpus_id=corpus_id, input_file=str(paths.input_json))
    cmd = [
        PYTHON_BIN,
        str(BASE_DIR / "data_processing.py"),
        str(paths.input_json),
        "--output-dir",
        str(BASE_DIR / "data"),
        "--model",
        model_name,
        "--corpus-ids",
        corpus_id,
        "--quiet",
    ]
    proc = run_cmd(cmd, cwd=BASE_DIR)
    if proc.returncode != 0:
        raise RuntimeError(
            f"data_processing.py failed (code={proc.returncode}): "
            f"{(proc.stderr or proc.stdout).strip()}"
        )

    corpus_path = BASE_DIR / "data" / paths.data_dataset_name / corpus_id
    if not corpus_path.exists():
        raise RuntimeError(f"Processed corpus path missing: {corpus_path}")

    emitter.emit(
        "preprocess_completed",
        corpus_id=corpus_id,
        dataset_name=paths.data_dataset_name,
        corpus_path=str(corpus_path),
    )
    return corpus_id, corpus_path


def load_document_map(corpus_path: Path) -> Dict[str, Any]:
    """Build deterministic doc-id-centric document metadata map."""
    metadata_path = corpus_path / "metadata.json"
    if not metadata_path.exists():
        return {"by_source_document_id": {}, "documents": []}

    with metadata_path.open("r", encoding="utf-8") as f:
        metadata = json.load(f)

    docs = metadata.get("documents") or []
    by_source_document_id: Dict[str, Any] = {}
    documents: List[Dict[str, Any]] = []

    for idx, doc in enumerate(docs):
        doc_id = doc.get("doc_id")
        if doc_id is not None:
            by_source_document_id[str(doc_id)] = doc_id

        documents.append(
            {
                "index": idx,
                "doc_id": doc_id,
                "filename": doc.get("filename"),
                "title": doc.get("title"),
                "doc_type": doc.get("doc_type"),
                "date": doc.get("date"),
                "sentence_count": doc.get("sentence_count"),
            }
        )

    return {
        "by_source_document_id": by_source_document_id,
        "documents": documents,
    }


def submit_slurm(
    request: Dict[str, Any],
    corpus_id: str,
    model_name: str,
    checklist_config: str,
    max_steps: int,
    reasoning_effort: str,
    resume: bool,
    debug: bool,
    output_base_dir: str,
    data_dataset_name: str,
) -> str:
    slurm = request.get("slurm") or {}
    partition = slurm.get("partition") or "nlprx-lab"
    qos = slurm.get("qos") or "short"

    exports = {
        "CORPUS_ID": corpus_id,
        "MODEL_NAME": model_name,
        "CHECKLIST_CONFIG": checklist_config,
        "MAX_STEPS": str(max_steps),
        "REASONING_EFFORT": reasoning_effort,
        "RESUME": bool_to_str(resume),
        "DEBUG": bool_to_str(debug),
        "OUTPUT_BASE_DIR": output_base_dir,
        "DATA_DIR": data_dataset_name,
    }
    export_blob = "ALL," + ",".join(f"{k}={v}" for k, v in exports.items())

    cmd = [
        slurm_executable("sbatch"),
        "--parsable",
        "--partition",
        partition,
        "--qos",
        qos,
        "--export",
        export_blob,
        str(SBATCH_SCRIPT),
    ]
    proc = run_cmd(cmd, cwd=BASE_DIR)
    if proc.returncode != 0:
        raise RuntimeError(f"sbatch failed (code={proc.returncode}): {(proc.stderr or '').strip()}")

    token = (proc.stdout or "").strip()
    if not token:
        raise RuntimeError("sbatch returned empty output; unable to parse job ID")
    return token.split(";")[0].strip()


def load_json_if_exists(path: Optional[Path]) -> Optional[Any]:
    if path is None or not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def find_latest_run_summary_path(output_dir: Path) -> Optional[Path]:
    run_files = sorted(output_dir.glob("run_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if run_files:
        return run_files[0]
    return None


def load_checklist_dict(path: Path) -> Dict[str, Any]:
    obj = load_json_if_exists(path)
    return obj if isinstance(obj, dict) else {}


def derive_completion_stats_from_checklist(
    checklist: Dict[str, Any],
    expected_total: Optional[int] = None,
) -> Dict[str, int]:
    total = expected_total if expected_total is not None else len(checklist)
    filled = sum(1 for v in checklist.values() if isinstance(v, dict) and (v.get("extracted") or []))
    empty = max(total - filled, 0)
    return {"filled": filled, "empty": empty, "total": total}


def summarize_job_artifacts(
    paths: Paths,
    checklist_config: str,
    config_name: str,
    job_id: str,
    max_steps: int,
    reasoning_effort: str,
    state: str,
    elapsed_seconds: float,
    timed_out: bool,
) -> Dict[str, Any]:
    run_summary_path = find_latest_run_summary_path(paths.output_dir)
    run_summary = load_json_if_exists(run_summary_path)
    stats = load_json_if_exists(paths.stats_path)
    raw_checklist = load_checklist_dict(paths.agent_checklist_path)

    completion_stats: Dict[str, Any] = {}
    if isinstance(run_summary, dict):
        completion_stats = run_summary.get("completion_stats") or {}
    if not completion_stats:
        completion_stats = derive_completion_stats_from_checklist(raw_checklist)

    token_stats: Dict[str, Any] = {}
    if isinstance(stats, dict):
        token_stats = {
            "steps": stats.get("steps"),
            "total_system_prompt_tokens": stats.get("total_system_prompt_tokens"),
            "total_user_prompt_tokens": stats.get("total_user_prompt_tokens"),
            "total_completion_tokens": stats.get("total_completion_tokens"),
        }

    derived_state_path = paths.output_dir / "derived_state.json"
    return {
        "config_name": config_name,
        "checklist_config": checklist_config,
        "job_id": job_id,
        "max_steps": max_steps,
        "reasoning_effort": reasoning_effort,
        "state": state,
        "timed_out": timed_out,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "completion_stats": completion_stats,
        "token_usage": token_stats,
        "output_dir": str(paths.output_dir),
        "checklist_path": str(paths.agent_checklist_path),
        "ledger_path": str(paths.ledger_path),
        "stats_path": str(paths.stats_path),
        "run_summary_path": str(run_summary_path) if run_summary_path else None,
        "derived_state_path": str(derived_state_path) if derived_state_path.exists() else None,
        "slurm_log_path": str(paths.slurm_log_path) if paths.slurm_log_path else None,
        "agent_log_path": str(paths.agent_log_path),
    }


def write_checklist_ndjson(checklist: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for key, value in checklist.items():
            if isinstance(value, dict):
                row = {
                    "key": key,
                    "extracted": value.get("extracted", []),
                    "last_updated": value.get("last_updated"),
                }
            else:
                row = {"key": key, "value": value}
            f.write(json.dumps(row, ensure_ascii=True) + "\n")


def read_text_len(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8") as f:
            return len(f.read())
    except UnicodeDecodeError:
        with path.open("r", encoding="latin-1") as f:
            return len(f.read())


def convert_checklist_to_offsets(checklist: Dict[str, Any], corpus_path: Path) -> Dict[str, Any]:
    """Convert sentence-span evidence to offset-only evidence."""
    metadata_path = corpus_path / "metadata.json"
    if not metadata_path.exists():
        raise RuntimeError(f"Missing corpus metadata for offset conversion: {metadata_path}")

    with metadata_path.open("r", encoding="utf-8") as f:
        metadata = json.load(f)

    documents = metadata.get("documents") or []
    docs_by_id: Dict[str, Dict[str, Any]] = {}
    for doc in documents:
        doc_id = doc.get("doc_id")
        if doc_id is not None:
            docs_by_id[str(doc_id)] = doc

    sentence_cache: Dict[str, Dict[int, Dict[str, Any]]] = {}
    text_len_cache: Dict[str, int] = {}

    def get_sentence_map(doc_id: str) -> Dict[int, Dict[str, Any]]:
        if doc_id in sentence_cache:
            return sentence_cache[doc_id]
        doc = docs_by_id.get(doc_id)
        if not doc:
            raise RuntimeError(f"Unknown source_document_id in evidence: {doc_id}")
        sidecar_file = doc.get("sentence_index_file")
        if not sidecar_file:
            raise RuntimeError(f"Missing sentence_index_file for doc_id={doc_id}")
        sidecar_path = corpus_path / sidecar_file
        if not sidecar_path.exists():
            raise RuntimeError(f"Missing sentence sidecar for doc_id={doc_id}: {sidecar_path}")
        with sidecar_path.open("r", encoding="utf-8") as f:
            sidecar = json.load(f)
        sentence_map: Dict[int, Dict[str, Any]] = {}
        for s in sidecar.get("sentences") or []:
            sid = int(s["sentence_id"])
            sentence_map[sid] = {
                "start_char": int(s["start_char"]),
                "end_char": int(s["end_char"]),
            }
        sentence_cache[doc_id] = sentence_map
        return sentence_map

    def get_text_len(doc_id: str) -> int:
        if doc_id in text_len_cache:
            return text_len_cache[doc_id]
        doc = docs_by_id.get(doc_id)
        if not doc:
            raise RuntimeError(f"Unknown source_document_id in evidence: {doc_id}")
        filename = doc.get("filename")
        if not filename:
            raise RuntimeError(f"Missing filename for doc_id={doc_id}")
        text_path = corpus_path / filename
        if not text_path.exists():
            raise RuntimeError(f"Missing text file for doc_id={doc_id}: {text_path}")
        text_len_cache[doc_id] = read_text_len(text_path)
        return text_len_cache[doc_id]

    converted: Dict[str, Any] = {}
    for key, item in checklist.items():
        if not isinstance(item, dict):
            converted[key] = item
            continue

        new_item = dict(item)
        new_extracted = []
        for extracted in item.get("extracted", []):
            if not isinstance(extracted, dict):
                continue
            new_ext = dict(extracted)
            new_evidence = []
            for ev in extracted.get("evidence", []):
                if not isinstance(ev, dict):
                    continue
                doc_id = str(ev.get("source_document_id", ""))
                if not doc_id:
                    raise RuntimeError(f"{key}: evidence missing source_document_id")
                if "start_sentence" not in ev or "end_sentence" not in ev:
                    raise RuntimeError(f"{key}: evidence for doc_id={doc_id} missing sentence span")
                start_sentence = int(ev["start_sentence"])
                end_sentence = int(ev["end_sentence"])
                if start_sentence < 1 or end_sentence < start_sentence:
                    raise RuntimeError(
                        f"{key}: invalid sentence span {start_sentence}-{end_sentence} for doc_id={doc_id}"
                    )

                sentence_map = get_sentence_map(doc_id)
                start_rec = sentence_map.get(start_sentence)
                end_rec = sentence_map.get(end_sentence)
                if not start_rec or not end_rec:
                    raise RuntimeError(
                        f"{key}: sentence span {start_sentence}-{end_sentence} out of range for doc_id={doc_id}"
                    )

                start_offset = int(start_rec["start_char"])
                end_offset = int(end_rec["end_char"])
                text_len = get_text_len(doc_id)
                if not (0 <= start_offset < end_offset <= text_len):
                    raise RuntimeError(
                        f"{key}: invalid offsets [{start_offset}, {end_offset}) for doc_id={doc_id}; "
                        f"text length={text_len}"
                    )

                new_evidence.append(
                    {
                        "source_document_id": doc_id,
                        "start_offset": start_offset,
                        "end_offset": end_offset,
                    }
                )

            new_ext["evidence"] = new_evidence
            new_extracted.append(new_ext)

        new_item["extracted"] = new_extracted
        converted[key] = new_item

    return converted


def build_artifact_bundle(
    paths: Paths,
    run_id: str,
    document_map: Dict[str, Any],
    corpus_path: Path,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    checklist_obj = load_json_if_exists(paths.agent_checklist_path)
    raw_agent_checklist = checklist_obj if isinstance(checklist_obj, dict) else {}
    checklist = convert_checklist_to_offsets(raw_agent_checklist, corpus_path)

    run_summary_path: Optional[Path] = None
    run_files = sorted(paths.output_dir.glob("run_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if run_files:
        run_summary_path = run_files[0]
    run_summary = load_json_if_exists(run_summary_path)
    stats = load_json_if_exists(paths.stats_path)

    write_json(paths.document_map_path, document_map)
    write_json(paths.final_checklist_path, checklist)
    write_checklist_ndjson(checklist, paths.checklist_ndjson_path)

    payload = {
        "run_id": run_id,
        "output_dir": str(paths.output_dir),
        "checklist_path": str(paths.final_checklist_path),
        "raw_agent_checklist_path": str(paths.agent_checklist_path),
        "ledger_path": str(paths.ledger_path),
        "stats_path": str(paths.stats_path),
        "agent_log_path": str(paths.agent_log_path),
        "slurm_log_path": str(paths.slurm_log_path) if paths.slurm_log_path else None,
        "corpus_path": str(corpus_path),
        "offset_basis": {
            "type": "character_offsets",
            "index_base": 0,
            "range_semantics": "half_open",
            "text_source": str(corpus_path),
        },
        "document_map": document_map,
        "checklist": checklist,
        "run_summary": run_summary,
        "run_summary_path": str(run_summary_path) if run_summary_path else None,
        "stats": stats,
    }
    if extra_metadata:
        payload.update(extra_metadata)
    write_json(paths.result_payload_path, payload)

    completion_stats: Dict[str, Any] = {}
    if isinstance(run_summary, dict):
        completion_stats = run_summary.get("completion_stats") or {}
    if not completion_stats:
        total = len(checklist)
        filled = sum(1 for v in checklist.values() if isinstance(v, dict) and (v.get("extracted") or []))
        completion_stats = {"filled": filled, "empty": max(total - filled, 0), "total": total}

    manifest = {
        "run_id": run_id,
        "created_at": utc_now_iso(),
        "artifacts": {
            "events_path": str(paths.events_path),
            "request_path": str(paths.request_path),
            "result_payload_path": str(paths.result_payload_path),
            "checklist_path": str(paths.final_checklist_path),
            "raw_agent_checklist_path": str(paths.agent_checklist_path),
            "checklist_ndjson_path": str(paths.checklist_ndjson_path),
            "document_map_path": str(paths.document_map_path),
            "stats_path": str(paths.stats_path),
            "run_summary_path": str(run_summary_path) if run_summary_path else None,
            "slurm_log_path": str(paths.slurm_log_path) if paths.slurm_log_path else None,
            "agent_log_path": str(paths.agent_log_path),
            "output_dir": str(paths.output_dir),
        },
        "completion_stats": completion_stats,
    }
    if extra_metadata:
        manifest.update(extra_metadata)
    write_json(paths.manifest_path, manifest)

    return {
        "run_id": run_id,
        "run_dir": str(paths.run_dir),
        "events_path": str(paths.events_path),
        "manifest_path": str(paths.manifest_path),
        "result_payload_path": str(paths.result_payload_path),
        "checklist_path": str(paths.final_checklist_path),
        "raw_agent_checklist_path": str(paths.agent_checklist_path),
        "checklist_ndjson_path": str(paths.checklist_ndjson_path),
        "document_map_path": str(paths.document_map_path),
        "stats_path": str(paths.stats_path),
        "run_summary_path": str(run_summary_path) if run_summary_path else None,
        "slurm_log_path": str(paths.slurm_log_path) if paths.slurm_log_path else None,
        "agent_log_path": str(paths.agent_log_path),
        "output_dir": str(paths.output_dir),
        "completion_stats": completion_stats,
    }


def run_slurm_extract_strategy(args: argparse.Namespace) -> int:
    """Run SLURM extraction with explicit checklist strategy (all vs individual)."""
    emitter = Emitter(args.request_id or "unknown_request")
    try:
        request = parse_stdin_json()
        if "run_id" in request:
            raise ValueError("run_id is controller-generated; do not provide run_id in request")
        run_id = validate_run_id(generate_run_id())

        input_payload = normalize_input_payload(request)
        corpus_id = str(input_payload["corpus_id"])
        model_name = request.get("model", "unsloth/gpt-oss-20b-BF16")
        checklist_strategy = parse_checklist_strategy(request)
        checklist_spec = parse_checklist_spec(request, strategy=checklist_strategy)
        focus_context = parse_optional_focus_context(request.get("focus_context"), "focus_context")
        resume = bool(request.get("resume", False))
        debug = bool(request.get("debug", False))

        run_max_steps: Optional[int] = None
        run_reasoning_effort: Optional[str] = None
        if checklist_strategy == "all":
            run_max_steps = require_positive_int(request.get("max_steps", 200), "max_steps")
            run_reasoning_effort = require_reasoning_effort(
                request.get("reasoning_effort", "medium"),
                "reasoning_effort",
            )
        else:
            if "max_steps" in request:
                raise ValueError(
                    "`max_steps` is not allowed when checklist_strategy='individual'; "
                    "provide per-item `checklist_spec.checklist_items[].max_steps`"
                )
            if "reasoning_effort" in request:
                raise ValueError(
                    "`reasoning_effort` is not allowed when checklist_strategy='individual'; "
                    "provide per-item `checklist_spec.checklist_items[].reasoning_effort`"
                )

        item_runtime_settings: List[Dict[str, Any]] = []
        if checklist_strategy == "all":
            item_runtime_settings.append(
                {
                    "item_index": 1,
                    "key": "__all__",
                    "max_steps": run_max_steps,
                    "reasoning_effort": run_reasoning_effort,
                }
            )
        else:
            for idx, item in enumerate(checklist_spec["items"], start=1):
                item_runtime_settings.append(
                    {
                        "item_index": idx,
                        "key": item["key"],
                        "max_steps": item["max_steps"],
                        "reasoning_effort": item["reasoning_effort"],
                    }
                )

        run_dir = RUNS_BASE / run_id
        if run_dir.exists():
            raise ValueError(f"run_id already exists: {run_dir}")
        run_dir.mkdir(parents=True, exist_ok=False)

        checklist_configs = materialize_checklist_configs(
            run_dir,
            checklist_spec,
            focus_context=focus_context,
        )

        planning_max_steps = item_runtime_settings[0]["max_steps"]

        planning_paths = build_paths(
            run_id=run_id,
            corpus_id=corpus_id,
            model_name=model_name,
            checklist_config=checklist_configs[0],
            max_steps=planning_max_steps,
            resume=resume,
            job_id=None,
        )

        emitter = Emitter(run_id, mirror_path=planning_paths.events_path)
        controller_started_at = utc_now_iso()
        controller_start = time.monotonic()
        emitter.emit(
            "started",
            mode="slurm_extract_strategy",
            pid=os.getpid(),
            run_id=run_id,
            checklist_strategy=checklist_strategy,
            jobs_planned=len(checklist_configs),
        )

        write_json(planning_paths.request_path, request)

        emitter.emit(
            "request_validated",
            run_id=run_id,
            corpus_id=corpus_id,
            model=model_name,
            checklist_strategy=checklist_strategy,
            max_steps=run_max_steps,
            reasoning_effort=run_reasoning_effort,
            jobs_planned=len(checklist_configs),
            checklist_items_count=len(checklist_spec["items"]),
            generated_checklist_configs=checklist_configs,
            item_runtime_settings=item_runtime_settings,
            focus_context=focus_context,
            run_dir=str(planning_paths.run_dir),
        )

        _, corpus_path = run_preprocess(emitter, input_payload, model_name, planning_paths)
        document_map = load_document_map(corpus_path)
        emitter.emit("document_map_ready", run_id=run_id, document_count=len(document_map.get("documents", [])))

        output_base_dir = f"controller/runs/{run_id}/agent_output"
        poll_seconds = max(args.poll_seconds, 0.5)
        max_wait_seconds = max(args.max_wait_seconds, 10)

        item_results: List[Dict[str, Any]] = []
        merged_raw_checklist: Dict[str, Any] = {}

        for idx, checklist_config in enumerate(checklist_configs, start=1):
            config_name = Path(checklist_config).stem
            item_start = time.monotonic()
            item_runtime = item_runtime_settings[idx - 1]
            item_max_steps = int(item_runtime["max_steps"])
            item_reasoning_effort = str(item_runtime["reasoning_effort"])

            job_id = submit_slurm(
                request=request,
                corpus_id=corpus_id,
                model_name=model_name,
                checklist_config=checklist_config,
                max_steps=item_max_steps,
                reasoning_effort=item_reasoning_effort,
                resume=resume,
                debug=debug,
                output_base_dir=output_base_dir,
                data_dataset_name=planning_paths.data_dataset_name,
            )

            item_paths = build_paths(
                run_id=run_id,
                corpus_id=corpus_id,
                model_name=model_name,
                checklist_config=checklist_config,
                max_steps=item_max_steps,
                resume=resume,
                job_id=job_id,
            )

            emitter.emit(
                "slurm_submitted",
                run_id=run_id,
                checklist_strategy=checklist_strategy,
                item_index=idx,
                items_total=len(checklist_configs),
                checklist_config=checklist_config,
                config_name=config_name,
                job_id=job_id,
                max_steps=item_max_steps,
                reasoning_effort=item_reasoning_effort,
                output_dir=str(item_paths.output_dir),
                ledger_path=str(item_paths.ledger_path),
                slurm_log_path=str(item_paths.slurm_log_path) if item_paths.slurm_log_path else None,
            )

            if item_paths.ledger_path.exists():
                st = item_paths.ledger_path.stat()
                ledger_pos = st.st_size
                ledger_identity: Optional[Tuple[int, int]] = (st.st_dev, st.st_ino)
            else:
                ledger_pos = 0
                ledger_identity = None
            seen_steps: Set[int] = set()

            state_started = time.monotonic()
            last_state = None
            timed_out = False
            final_state = "UNKNOWN"
            while True:
                state = slurm_state(job_id)
                if state != last_state:
                    emitter.emit(
                        "slurm_state",
                        run_id=run_id,
                        checklist_strategy=checklist_strategy,
                        item_index=idx,
                        items_total=len(checklist_configs),
                        checklist_config=checklist_config,
                        config_name=config_name,
                        job_id=job_id,
                        state=state,
                    )
                    last_state = state

                ledger_pos, ledger_identity = emit_new_steps(
                    emitter,
                    item_paths.ledger_path,
                    ledger_pos,
                    seen_steps,
                    ledger_identity,
                    extra_fields={
                        "item_index": idx,
                        "items_total": len(checklist_configs),
                        "checklist_config": checklist_config,
                        "config_name": config_name,
                        "job_id": job_id,
                    },
                )

                if state in TERMINAL_STATES:
                    final_state = state
                    break

                if time.monotonic() - state_started > max_wait_seconds:
                    run_cmd([slurm_executable("scancel"), job_id])
                    timed_out = True
                    final_state = "TIMEOUT"
                    emitter.emit(
                        "item_timeout",
                        run_id=run_id,
                        checklist_strategy=checklist_strategy,
                        item_index=idx,
                        items_total=len(checklist_configs),
                        checklist_config=checklist_config,
                        config_name=config_name,
                        job_id=job_id,
                        max_wait_seconds=max_wait_seconds,
                    )
                    break

                time.sleep(poll_seconds)

            item_elapsed = time.monotonic() - item_start
            item_summary = summarize_job_artifacts(
                item_paths,
                checklist_config=checklist_config,
                config_name=config_name,
                job_id=job_id,
                max_steps=item_max_steps,
                reasoning_effort=item_reasoning_effort,
                state=final_state,
                elapsed_seconds=item_elapsed,
                timed_out=timed_out,
            )
            item_results.append(item_summary)

            raw_item_checklist = load_checklist_dict(item_paths.agent_checklist_path)
            if raw_item_checklist:
                merged_raw_checklist.update(raw_item_checklist)

            if final_state == "COMPLETED":
                emitter.emit(
                    "item_completed",
                    run_id=run_id,
                    checklist_strategy=checklist_strategy,
                    item_index=idx,
                    items_total=len(checklist_configs),
                    checklist_config=checklist_config,
                    config_name=config_name,
                    job_id=job_id,
                    max_steps=item_max_steps,
                    reasoning_effort=item_reasoning_effort,
                    state=final_state,
                    elapsed_seconds=round(item_elapsed, 3),
                    completion_stats=item_summary.get("completion_stats"),
                )
            else:
                emitter.emit(
                    "item_failed",
                    run_id=run_id,
                    checklist_strategy=checklist_strategy,
                    item_index=idx,
                    items_total=len(checklist_configs),
                    checklist_config=checklist_config,
                    config_name=config_name,
                    job_id=job_id,
                    max_steps=item_max_steps,
                    reasoning_effort=item_reasoning_effort,
                    state=final_state,
                    timed_out=timed_out,
                    elapsed_seconds=round(item_elapsed, 3),
                    completion_stats=item_summary.get("completion_stats"),
                )

        converted_checklist: Dict[str, Any] = {}
        conversion_error: Optional[str] = None
        if merged_raw_checklist:
            try:
                converted_checklist = convert_checklist_to_offsets(merged_raw_checklist, corpus_path)
            except Exception as exc:
                conversion_error = str(exc)
                converted_checklist = {}
                emitter.emit(
                    "warning",
                    run_id=run_id,
                    message="Failed to convert aggregated checklist to offsets",
                    error=conversion_error,
                )

        write_json(planning_paths.document_map_path, document_map)
        write_json(planning_paths.final_checklist_path, converted_checklist)
        write_checklist_ndjson(converted_checklist, planning_paths.checklist_ndjson_path)

        expected_total = len(checklist_configs) if checklist_strategy == "individual" else None
        completion_stats = derive_completion_stats_from_checklist(
            converted_checklist,
            expected_total=expected_total,
        )

        jobs_total = len(item_results)
        jobs_completed = sum(1 for item in item_results if item.get("state") == "COMPLETED")
        jobs_failed = jobs_total - jobs_completed

        controller_finished_at = utc_now_iso()
        controller_elapsed = round(time.monotonic() - controller_start, 3)
        controller_timing = {
            "started_at": controller_started_at,
            "finished_at": controller_finished_at,
            "elapsed_seconds": controller_elapsed,
        }

        result_payload = {
            "run_id": run_id,
            "checklist_strategy": checklist_strategy,
            "checklist_source": "inline_spec",
            "checklist_items_count": len(checklist_spec["items"]),
            "generated_checklist_configs": checklist_configs,
            "corpus_id": corpus_id,
            "model": model_name,
            "max_steps": run_max_steps,
            "reasoning_effort": run_reasoning_effort,
            "item_runtime_settings": item_runtime_settings,
            "resume": resume,
            "debug": debug,
            "focus_context": focus_context,
            "controller_timing": controller_timing,
            "jobs_total": jobs_total,
            "jobs_completed": jobs_completed,
            "jobs_failed": jobs_failed,
            "jobs": item_results,
            "checklist": converted_checklist,
            "completion_stats": completion_stats,
            "checklist_path": str(planning_paths.final_checklist_path),
            "checklist_ndjson_path": str(planning_paths.checklist_ndjson_path),
            "document_map_path": str(planning_paths.document_map_path),
            "corpus_path": str(corpus_path),
            "offset_basis": {
                "type": "character_offsets",
                "index_base": 0,
                "range_semantics": "half_open",
                "text_source": str(corpus_path),
            },
            "conversion_error": conversion_error,
        }
        write_json(planning_paths.result_payload_path, result_payload)

        manifest = {
            "run_id": run_id,
            "created_at": controller_finished_at,
            "checklist_strategy": checklist_strategy,
            "checklist_source": "inline_spec",
            "checklist_items_count": len(checklist_spec["items"]),
            "generated_checklist_configs": checklist_configs,
            "max_steps": run_max_steps,
            "reasoning_effort": run_reasoning_effort,
            "item_runtime_settings": item_runtime_settings,
            "focus_context": focus_context,
            "controller_timing": controller_timing,
            "jobs_total": jobs_total,
            "jobs_completed": jobs_completed,
            "jobs_failed": jobs_failed,
            "artifacts": {
                "events_path": str(planning_paths.events_path),
                "request_path": str(planning_paths.request_path),
                "result_payload_path": str(planning_paths.result_payload_path),
                "checklist_path": str(planning_paths.final_checklist_path),
                "checklist_ndjson_path": str(planning_paths.checklist_ndjson_path),
                "document_map_path": str(planning_paths.document_map_path),
                "manifest_path": str(planning_paths.manifest_path),
            },
            "completion_stats": completion_stats,
        }
        write_json(planning_paths.manifest_path, manifest)

        final_bundle = {
            "run_id": run_id,
            "run_dir": str(planning_paths.run_dir),
            "events_path": str(planning_paths.events_path),
            "manifest_path": str(planning_paths.manifest_path),
            "result_payload_path": str(planning_paths.result_payload_path),
            "checklist_path": str(planning_paths.final_checklist_path),
            "checklist_ndjson_path": str(planning_paths.checklist_ndjson_path),
            "document_map_path": str(planning_paths.document_map_path),
            "completion_stats": completion_stats,
            "controller_timing": controller_timing,
            "checklist_strategy": checklist_strategy,
            "checklist_source": "inline_spec",
            "checklist_items_count": len(checklist_spec["items"]),
            "generated_checklist_configs": checklist_configs,
            "max_steps": run_max_steps,
            "reasoning_effort": run_reasoning_effort,
            "item_runtime_settings": item_runtime_settings,
            "focus_context": focus_context,
            "jobs_total": jobs_total,
            "jobs_completed": jobs_completed,
            "jobs_failed": jobs_failed,
        }

        if jobs_failed == 0:
            emitter.emit("completed", state="COMPLETED", **final_bundle)
            return 0

        emitter.emit(
            "failed",
            state="PARTIAL",
            partial_results=True,
            **final_bundle,
        )
        return 4
    except Exception as exc:
        emitter.emit(
            "failed",
            error=str(exc),
            exception_type=type(exc).__name__,
            traceback=traceback.format_exc(),
            exit_code=1,
        )
        return 1
    finally:
        emitter.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NDJSON controller for smoke and SLURM extraction")
    parser.add_argument(
        "--mode",
        choices=["smoke", "slurm_extract_strategy"],
        default="smoke",
        help="Controller mode (default: smoke)",
    )
    parser.add_argument("--request-id", help="Request identifier (required for smoke mode)")

    # Smoke options
    parser.add_argument("--ticks", type=int, default=5, help="Number of heartbeat events to emit")
    parser.add_argument("--tick-seconds", type=float, default=1.0, help="Seconds between heartbeat events")
    parser.add_argument(
        "--fail-at",
        type=int,
        default=-1,
        help="1-based heartbeat index that should trigger a synthetic failure",
    )
    parser.add_argument(
        "--payload",
        default=None,
        help="Optional JSON string (or plain text) to echo in the started event",
    )

    # SLURM mode options
    parser.add_argument("--poll-seconds", type=float, default=2.0, help="SLURM poll interval")
    parser.add_argument(
        "--max-wait-seconds",
        type=float,
        default=6 * 60 * 60,
        help="Maximum wait before controller cancels the job",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.mode == "smoke":
            return run_smoke(args)
        return run_slurm_extract_strategy(args)
    except KeyboardInterrupt:
        request_id = args.request_id or "unknown_request"
        emitter = Emitter(request_id)
        emitter.emit("failed", error="Interrupted by keyboard signal", exit_code=130)
        emitter.close()
        return 130
    except Exception as exc:  # pragma: no cover - orchestration utility
        request_id = args.request_id or "unknown_request"
        emitter = Emitter(request_id)
        emitter.emit(
            "failed",
            error=str(exc),
            exception_type=type(exc).__name__,
            traceback=traceback.format_exc(),
            exit_code=1,
        )
        emitter.close()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
