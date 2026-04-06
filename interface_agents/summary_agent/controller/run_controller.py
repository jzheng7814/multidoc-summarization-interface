#!/usr/bin/env python3
"""SSH-stream controller for summary-agent SLURM execution.

Reads one JSON request from stdin and emits NDJSON events to stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
import uuid
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
load_dotenv_file(Path(os.environ.get("INTERFACE_SUMMARY_AGENT_ENV_FILE", str(DEFAULT_ENV_PATH))))

BASE_DIR = Path(
    os.environ.get("INTERFACE_SUMMARY_AGENT_BASE_DIR", str(DEFAULT_BASE_DIR))
).expanduser().resolve()
EXTRACTION_BASE_DIR = Path(
    os.environ.get(
        "INTERFACE_SUMMARY_AGENT_EXTRACTION_BASE_DIR",
        os.environ.get(
            "INTERFACE_CHECKLIST_AGENT_BASE_DIR",
            str(BASE_DIR.parent / "checklist_agent"),
        ),
    )
).expanduser().resolve()
SBATCH_SCRIPT = Path(
    os.environ.get(
        "INTERFACE_SUMMARY_AGENT_SBATCH_SCRIPT",
        str(BASE_DIR / "run_summary_agent_native.sbatch"),
    )
).expanduser()
RUNS_BASE = Path(
    os.environ.get(
        "INTERFACE_SUMMARY_AGENT_RUNS_BASE",
        str(BASE_DIR / "controller" / "runs"),
    )
).expanduser()
SLURM_BIN_DIR = Path(
    os.environ.get("INTERFACE_SUMMARY_AGENT_SLURM_BIN_DIR", "/opt/slurm/Ubuntu-20.04/current/bin")
).expanduser()
DEFAULT_PYTHON_BIN = os.environ.get(
    "INTERFACE_SUMMARY_AGENT_PYTHON_BIN",
    sys.executable,
)
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


@dataclass
class Paths:
    run_dir: Path
    events_path: Path
    request_path: Path
    agent_request_path: Path
    input_json: Path
    data_dataset_name: str
    output_dir: Path
    ledger_path: Path
    summary_state_path: Path
    stats_path: Path
    agent_log_path: Path
    slurm_log_path: Optional[Path]
    document_map_path: Path
    summary_json_path: Path
    result_payload_path: Path
    manifest_path: Path


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def load_json_if_exists(path: Optional[Path]) -> Optional[Any]:
    if path is None or not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


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


def slurm_executable(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    return str(SLURM_BIN_DIR / name)


def run_cmd(cmd: List[str], cwd: Optional[Path] = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        check=False,
    )


def normalize_slurm_state(raw_state: str) -> str:
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


def require_non_empty_string(value: Any, field_path: str) -> str:
    if value is None:
        raise ValueError(f"`{field_path}` is required")
    if not isinstance(value, str):
        raise ValueError(f"`{field_path}` must be a string")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"`{field_path}` must not be empty")
    return cleaned


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
    cleaned = value.strip().lower()
    if cleaned not in ALLOWED_REASONING_EFFORTS:
        allowed = ", ".join(sorted(ALLOWED_REASONING_EFFORTS))
        raise ValueError(f"`{field_path}` must be one of: {allowed}")
    return cleaned


def parse_optional_focus_context(value: Any, field_path: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"`{field_path}` must be a string when provided")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"`{field_path}` must not be empty when provided")
    return cleaned


def normalize_single_case(payload: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(payload.get("case"), dict):
        case = dict(payload["case"])
    elif isinstance(payload.get("input_case"), dict):
        case = dict(payload["input_case"])
    elif isinstance(payload.get("cases"), list):
        cases = payload["cases"]
        if len(cases) != 1:
            raise ValueError("Only one case per request is supported")
        if not isinstance(cases[0], dict):
            raise ValueError("cases[0] must be an object")
        case = dict(cases[0])
    else:
        raise ValueError("Request must provide one case in `case`, `input_case`, or single-entry `cases`")

    if "case_id" not in case and payload.get("case_id") is not None:
        case["case_id"] = payload["case_id"]

    if "case_id" not in case:
        raise ValueError("Case payload must include `case_id`")

    return case


def normalize_checklist(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict) or not raw:
        raise ValueError("`checklist` is required and must be a non-empty object")

    checklist: Dict[str, Any] = {}
    for key, item in raw.items():
        key_name = str(key).strip()
        if not key_name:
            raise ValueError("`checklist` keys must be non-empty strings")

        if not isinstance(item, dict):
            raise ValueError(f"`checklist.{key_name}` must be an object")

        extracted = item.get("extracted")
        if extracted is None:
            extracted = []
        if not isinstance(extracted, list):
            raise ValueError(f"`checklist.{key_name}.extracted` must be a list")

        normalized_extracted = []
        for idx, ext in enumerate(extracted):
            path = f"checklist.{key_name}.extracted[{idx}]"
            if not isinstance(ext, dict):
                raise ValueError(f"`{path}` must be an object")
            value = str(ext.get("value") or "").strip()
            evidence = ext.get("evidence") or []
            if not isinstance(evidence, list):
                raise ValueError(f"`{path}.evidence` must be a list")
            normalized_extracted.append({"value": value, "evidence": evidence})

        checklist[key_name] = {"extracted": normalized_extracted}

    return checklist


def normalize_checklist_definitions(raw: Any) -> Dict[str, str]:
    if not isinstance(raw, dict) or not raw:
        raise ValueError("`checklist_definitions` is required and must be a non-empty object")

    definitions: Dict[str, str] = {}
    for key, value in raw.items():
        key_name = str(key).strip()
        if not key_name:
            raise ValueError("`checklist_definitions` keys must be non-empty strings")
        if not isinstance(value, str):
            raise ValueError(f"`checklist_definitions.{key_name}` must be a string")
        text = value.strip()
        if not text:
            raise ValueError(f"`checklist_definitions.{key_name}` must not be empty")
        definitions[key_name] = text
    return definitions


def normalize_summary_constraints(raw: Any) -> List[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("`summary_constraints` must be a list when provided")

    constraints: List[str] = []
    for idx, item in enumerate(raw):
        if not isinstance(item, str):
            raise ValueError(f"`summary_constraints[{idx}]` must be a string")
        text = item.strip()
        if not text:
            raise ValueError(f"`summary_constraints[{idx}]` must not be empty")
        constraints.append(text)
    return constraints


def build_paths(
    *,
    run_id: str,
    case_id: str,
    model_name: str,
    max_steps: int,
    resume: bool,
    job_id: Optional[str] = None,
) -> Paths:
    run_dir = RUNS_BASE / run_id
    model_suffix = model_name.split("/")[-1]
    output_base_dir = f"controller/runs/{run_id}/agent_output"
    output_dir = BASE_DIR / output_base_dir / model_suffix / case_id / "summary_agent"

    log_name = f"{case_id}_summary_agent_steps{max_steps}"
    if resume:
        log_name += "_resume"
    agent_log_path = BASE_DIR / "agent_logs" / model_suffix / case_id / f"{log_name}.log"

    slurm_log_path = None
    if job_id:
        slurm_log_path = BASE_DIR / "agent_logs" / f"summary_agent_native_run-{job_id}.out"

    return Paths(
        run_dir=run_dir,
        events_path=run_dir / "events.ndjson",
        request_path=run_dir / "request.json",
        agent_request_path=run_dir / "agent_request.json",
        input_json=run_dir / f"controller_{run_id}.json",
        data_dataset_name=f"controller_{run_id}",
        output_dir=output_dir,
        ledger_path=output_dir / "ledger.jsonl",
        summary_state_path=output_dir / "summary_state.json",
        stats_path=output_dir / "stats.json",
        agent_log_path=agent_log_path,
        slurm_log_path=slurm_log_path,
        document_map_path=run_dir / "document_map.json",
        summary_json_path=run_dir / "summary.json",
        result_payload_path=run_dir / "result_payload.json",
        manifest_path=run_dir / "manifest.json",
    )


def run_preprocess(
    emitter: Emitter,
    *,
    case: Dict[str, Any],
    model_name: str,
    paths: Paths,
    python_bin: str,
) -> Tuple[str, Path]:
    case_id = str(case["case_id"])
    with paths.input_json.open("w", encoding="utf-8") as f:
        json.dump([case], f, ensure_ascii=False)

    emitter.emit("preprocess_started", case_id=case_id, input_file=str(paths.input_json))
    cmd = [
        python_bin,
        str(EXTRACTION_BASE_DIR / "data_processing.py"),
        str(paths.input_json),
        "--output-dir",
        str(EXTRACTION_BASE_DIR / "data"),
        "--model",
        model_name,
        "--case-ids",
        case_id,
        "--quiet",
    ]
    proc = run_cmd(cmd, cwd=EXTRACTION_BASE_DIR)
    if proc.returncode != 0:
        raise RuntimeError(
            f"data_processing.py failed (code={proc.returncode}): {(proc.stderr or proc.stdout).strip()}"
        )

    corpus_path = EXTRACTION_BASE_DIR / "data" / paths.data_dataset_name / case_id
    if not corpus_path.exists():
        raise RuntimeError(f"Processed corpus path missing: {corpus_path}")

    emitter.emit(
        "preprocess_completed",
        case_id=case_id,
        dataset_name=paths.data_dataset_name,
        corpus_path=str(corpus_path),
    )
    return case_id, corpus_path


def load_document_map(corpus_path: Path) -> Dict[str, Any]:
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


def _read_text_len(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8") as f:
            return len(f.read())
    except UnicodeDecodeError:
        with path.open("r", encoding="latin-1") as f:
            return len(f.read())


def convert_checklist_offsets_to_sentences(checklist: Dict[str, Any], corpus_path: Path) -> Dict[str, Any]:
    """Map checklist evidence offsets to sentence spans with overfetch.

    Overfetch behavior:
    - start_sentence uses the nearest sentence start at-or-left of start_offset.
    - end_sentence uses the first sentence end at-or-right of end_offset.
    """

    metadata_path = corpus_path / "metadata.json"
    if not metadata_path.exists():
        raise RuntimeError(f"Missing corpus metadata for offset conversion: {metadata_path}")

    with metadata_path.open("r", encoding="utf-8") as f:
        metadata = json.load(f)

    docs = metadata.get("documents") or []
    docs_by_id: Dict[str, Dict[str, Any]] = {}
    for doc in docs:
        doc_id = doc.get("doc_id")
        if doc_id is not None:
            docs_by_id[str(doc_id)] = doc

    sentence_cache: Dict[str, List[Dict[str, Any]]] = {}
    text_len_cache: Dict[str, int] = {}

    def load_sentences(doc_id: str) -> List[Dict[str, Any]]:
        if doc_id in sentence_cache:
            return sentence_cache[doc_id]

        doc = docs_by_id.get(doc_id)
        if not doc:
            raise RuntimeError(f"Unknown source_document_id in checklist evidence: {doc_id}")

        sidecar = doc.get("sentence_index_file")
        if not sidecar:
            raise RuntimeError(f"Missing sentence_index_file for doc_id={doc_id}")

        path = corpus_path / sidecar
        if not path.exists():
            raise RuntimeError(f"Missing sentence sidecar for doc_id={doc_id}: {path}")

        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)

        sentences = payload.get("sentences") or []
        normalized = []
        for record in sentences:
            normalized.append(
                {
                    "sentence_id": int(record["sentence_id"]),
                    "start_char": int(record["start_char"]),
                    "end_char": int(record["end_char"]),
                }
            )
        normalized.sort(key=lambda row: row["sentence_id"])
        if not normalized:
            raise RuntimeError(f"Sentence sidecar is empty for doc_id={doc_id}")

        sentence_cache[doc_id] = normalized
        return normalized

    def get_text_len(doc_id: str) -> int:
        if doc_id in text_len_cache:
            return text_len_cache[doc_id]

        doc = docs_by_id.get(doc_id)
        if not doc:
            raise RuntimeError(f"Unknown source_document_id in checklist evidence: {doc_id}")

        filename = doc.get("filename")
        if not filename:
            raise RuntimeError(f"Missing filename for doc_id={doc_id}")

        path = corpus_path / filename
        if not path.exists():
            raise RuntimeError(f"Missing text file for doc_id={doc_id}: {path}")

        text_len_cache[doc_id] = _read_text_len(path)
        return text_len_cache[doc_id]

    def start_sentence_for_offset(sentences: List[Dict[str, Any]], start_offset: int) -> int:
        chosen = sentences[0]["sentence_id"]
        for sentence in sentences:
            if sentence["start_char"] <= start_offset:
                chosen = sentence["sentence_id"]
            else:
                break
        return chosen

    def end_sentence_for_offset(sentences: List[Dict[str, Any]], end_offset: int) -> int:
        for sentence in sentences:
            if sentence["end_char"] >= end_offset:
                return sentence["sentence_id"]
        return sentences[-1]["sentence_id"]

    converted: Dict[str, Any] = {}
    for key, item in checklist.items():
        if not isinstance(item, dict):
            continue

        extracted_items = item.get("extracted") or []
        if not isinstance(extracted_items, list):
            raise RuntimeError(f"{key}: extracted must be a list")

        converted_extracted = []
        for ext_idx, ext in enumerate(extracted_items):
            if not isinstance(ext, dict):
                continue

            evidence_items = ext.get("evidence") or []
            if not isinstance(evidence_items, list):
                raise RuntimeError(f"{key}.extracted[{ext_idx}].evidence must be a list")

            converted_evidence = []
            for ev_idx, ev in enumerate(evidence_items):
                if not isinstance(ev, dict):
                    continue

                doc_id = str(ev.get("source_document_id") or "").strip()
                if not doc_id:
                    raise RuntimeError(f"{key}.extracted[{ext_idx}].evidence[{ev_idx}] missing source_document_id")

                if "start_sentence" in ev and "end_sentence" in ev:
                    start_sentence = int(ev["start_sentence"])
                    end_sentence = int(ev["end_sentence"])
                    if start_sentence < 1 or end_sentence < start_sentence:
                        raise RuntimeError(
                            f"{key}.extracted[{ext_idx}].evidence[{ev_idx}] has invalid sentence span"
                        )
                    converted_evidence.append(
                        {
                            "source_document_id": doc_id,
                            "start_sentence": start_sentence,
                            "end_sentence": end_sentence,
                            "start_offset": ev.get("start_offset"),
                            "end_offset": ev.get("end_offset"),
                        }
                    )
                    continue

                if "start_offset" not in ev or "end_offset" not in ev:
                    raise RuntimeError(
                        f"{key}.extracted[{ext_idx}].evidence[{ev_idx}] must include either sentence span or offsets"
                    )

                start_offset = int(ev["start_offset"])
                end_offset = int(ev["end_offset"])
                text_len = get_text_len(doc_id)
                if not (0 <= start_offset < end_offset <= text_len):
                    raise RuntimeError(
                        f"{key}.extracted[{ext_idx}].evidence[{ev_idx}] has invalid offsets "
                        f"[{start_offset}, {end_offset}) for doc_id={doc_id}; text_len={text_len}"
                    )

                sentences = load_sentences(doc_id)
                start_sentence = start_sentence_for_offset(sentences, start_offset)
                end_sentence = end_sentence_for_offset(sentences, end_offset)
                if end_sentence < start_sentence:
                    end_sentence = start_sentence

                converted_evidence.append(
                    {
                        "source_document_id": doc_id,
                        "start_sentence": start_sentence,
                        "end_sentence": end_sentence,
                        "start_offset": start_offset,
                        "end_offset": end_offset,
                    }
                )

            converted_extracted.append(
                {
                    "value": str(ext.get("value") or "").strip(),
                    "evidence": converted_evidence,
                }
            )

        converted[key] = {"extracted": converted_extracted}

    return converted


def submit_slurm(
    *,
    request: Dict[str, Any],
    case_id: str,
    model_name: str,
    max_steps: int,
    reasoning_effort: str,
    resume: bool,
    debug: bool,
    output_base_dir: str,
    data_dataset_name: str,
    agent_request_path: Path,
    k_recent_tool_outputs: int,
    prompt_config: Optional[str],
) -> str:
    slurm = request.get("slurm") or {}
    partition = slurm.get("partition") or "nlprx-lab"
    qos = slurm.get("qos") or "short"

    exports = {
        "CASE_ID": case_id,
        "MODEL_NAME": model_name,
        "MAX_STEPS": str(max_steps),
        "REASONING_EFFORT": reasoning_effort,
        "RESUME": bool_to_str(resume),
        "DEBUG": bool_to_str(debug),
        "OUTPUT_BASE_DIR": output_base_dir,
        "DATA_DIR": data_dataset_name,
        "REQUEST_JSON": str(agent_request_path),
        "K_RECENT_TOOL_OUTPUTS": str(k_recent_tool_outputs),
    }
    if prompt_config:
        exports["PROMPT_CONFIG"] = prompt_config

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
        raise RuntimeError(f"sbatch failed (code={proc.returncode}): {(proc.stderr or proc.stdout).strip()}")

    token = (proc.stdout or "").strip()
    if not token:
        raise RuntimeError("sbatch returned empty output; unable to parse job ID")
    return token.split(";", 1)[0].strip()


def emit_new_steps(
    emitter: Emitter,
    ledger_path: Path,
    read_pos: int,
    seen_steps: Set[int],
    file_identity: Optional[Tuple[int, int]],
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

        event = record.get("event", {}) if isinstance(record, dict) else {}
        step = record.get("step")
        if not isinstance(step, int):
            step = event.get("step") if isinstance(event, dict) else None

        if isinstance(step, int) and step not in seen_steps:
            seen_steps.add(step)
            tool_name = record.get("event_name") or event.get("tool_name")
            success = None
            if isinstance(event, dict):
                success = event.get("success")
            emitter.emit(
                "step_completed",
                step=step,
                tool_name=tool_name,
                success=success,
            )

    return read_pos, current_identity


def summarize_stats(summary_state: Dict[str, Any], summary_text: str) -> Dict[str, Any]:
    stats = summary_state.get("summary_stats") if isinstance(summary_state, dict) else None
    if isinstance(stats, dict):
        return {
            "paragraph_count": int(stats.get("paragraph_count", 0)),
            "character_count": int(stats.get("character_count", len(summary_text))),
            "non_empty": bool(stats.get("non_empty", bool(summary_text.strip()))),
        }
    return {
        "paragraph_count": 0,
        "character_count": len(summary_text),
        "non_empty": bool(summary_text.strip()),
    }


def find_latest_run_summary_path(output_dir: Path) -> Optional[Path]:
    run_files = sorted(output_dir.glob("run_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if run_files:
        return run_files[0]
    return None


def build_artifact_bundle(
    *,
    run_id: str,
    request_id: str,
    case_id: str,
    job_id: str,
    state: str,
    paths: Paths,
    request: Dict[str, Any],
    checklist_offsets: Dict[str, Any],
    checklist_sentence_spans: Dict[str, Any],
    document_map: Dict[str, Any],
    corpus_path: Path,
) -> Dict[str, Any]:
    summary_state_obj = load_json_if_exists(paths.summary_state_path)
    summary_state = summary_state_obj if isinstance(summary_state_obj, dict) else {}

    summary_text = ""
    if isinstance(summary_state.get("summary_text"), str):
        summary_text = str(summary_state.get("summary_text") or "")

    run_summary_path = find_latest_run_summary_path(paths.output_dir)
    run_summary = load_json_if_exists(run_summary_path)
    if not summary_text and isinstance(run_summary, dict):
        summary_text = str(run_summary.get("summary") or "")

    summary_stats = summarize_stats(summary_state, summary_text)
    stats = load_json_if_exists(paths.stats_path)

    write_json(paths.document_map_path, document_map)

    summary_payload = {
        "run_id": run_id,
        "request_id": request_id,
        "case_id": case_id,
        "summary": summary_text,
        "summary_stats": summary_stats,
        "summary_state": summary_state,
    }
    write_json(paths.summary_json_path, summary_payload)

    result_payload = {
        "run_id": run_id,
        "request_id": request_id,
        "job_id": job_id,
        "state": state,
        "case_id": case_id,
        "model": request.get("model", "unsloth/gpt-oss-20b-BF16"),
        "max_steps": request.get("max_steps"),
        "reasoning_effort": request.get("reasoning_effort"),
        "summary": summary_text,
        "summary_stats": summary_stats,
        "summary_state": summary_state,
        "checklist": checklist_offsets,
        "checklist_sentence_spans": checklist_sentence_spans,
        "checklist_definitions": request.get("checklist_definitions", {}),
        "focus_context": request.get("focus_context"),
        "offset_basis": {
            "type": "character_offsets",
            "index_base": 0,
            "range_semantics": "half_open",
            "text_source": str(corpus_path),
        },
        "document_map": document_map,
        "output_dir": str(paths.output_dir),
        "summary_path": str(paths.summary_json_path),
        "summary_state_path": str(paths.summary_state_path),
        "ledger_path": str(paths.ledger_path),
        "stats_path": str(paths.stats_path),
        "run_summary": run_summary,
        "run_summary_path": str(run_summary_path) if run_summary_path else None,
        "stats": stats,
        "agent_log_path": str(paths.agent_log_path),
        "slurm_log_path": str(paths.slurm_log_path) if paths.slurm_log_path else None,
        "corpus_path": str(corpus_path),
    }
    write_json(paths.result_payload_path, result_payload)

    manifest = {
        "run_id": run_id,
        "created_at": utc_now_iso(),
        "request_id": request_id,
        "job_id": job_id,
        "state": state,
        "summary_stats": summary_stats,
        "artifacts": {
            "events_path": str(paths.events_path),
            "request_path": str(paths.request_path),
            "agent_request_path": str(paths.agent_request_path),
            "result_payload_path": str(paths.result_payload_path),
            "manifest_path": str(paths.manifest_path),
            "summary_path": str(paths.summary_json_path),
            "summary_state_path": str(paths.summary_state_path),
            "document_map_path": str(paths.document_map_path),
            "ledger_path": str(paths.ledger_path),
            "stats_path": str(paths.stats_path),
            "run_summary_path": str(run_summary_path) if run_summary_path else None,
            "agent_log_path": str(paths.agent_log_path),
            "slurm_log_path": str(paths.slurm_log_path) if paths.slurm_log_path else None,
            "output_dir": str(paths.output_dir),
        },
    }
    write_json(paths.manifest_path, manifest)

    return {
        "run_id": run_id,
        "run_dir": str(paths.run_dir),
        "events_path": str(paths.events_path),
        "manifest_path": str(paths.manifest_path),
        "result_payload_path": str(paths.result_payload_path),
        "summary_path": str(paths.summary_json_path),
        "summary_state_path": str(paths.summary_state_path),
        "document_map_path": str(paths.document_map_path),
        "stats_path": str(paths.stats_path),
        "run_summary_path": str(run_summary_path) if run_summary_path else None,
        "slurm_log_path": str(paths.slurm_log_path) if paths.slurm_log_path else None,
        "agent_log_path": str(paths.agent_log_path),
        "output_dir": str(paths.output_dir),
        "summary_stats": summary_stats,
    }


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
            emitter.close()
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


def run_slurm_summarize_agent(args: argparse.Namespace) -> int:
    emitter = Emitter(args.request_id or "unknown_request")

    try:
        request = parse_stdin_json()
        if "run_id" in request:
            raise ValueError("run_id is controller-generated; do not provide run_id in request")

        run_id = validate_run_id(generate_run_id())
        request_id = str(request.get("request_id") or run_id)

        case = normalize_single_case(request)
        case_id = str(case["case_id"])

        checklist_offsets = normalize_checklist(request.get("checklist"))
        checklist_definitions = normalize_checklist_definitions(request.get("checklist_definitions"))
        summary_constraints = normalize_summary_constraints(request.get("summary_constraints"))
        focus_context = parse_optional_focus_context(request.get("focus_context"), "focus_context")

        model_name = str(request.get("model") or "unsloth/gpt-oss-20b-BF16")
        max_steps = require_positive_int(request.get("max_steps", 200), "max_steps")
        reasoning_effort = require_reasoning_effort(
            request.get("reasoning_effort", "medium"),
            "reasoning_effort",
        )
        resume = bool(request.get("resume", False))
        debug = bool(request.get("debug", False))
        k_recent_tool_outputs = require_positive_int(
            request.get("k_recent_tool_outputs", 5),
            "k_recent_tool_outputs",
        )
        prompt_config = request.get("prompt_config")
        if prompt_config is not None:
            prompt_config = require_non_empty_string(prompt_config, "prompt_config")

        python_bin = str(request.get("python_bin") or args.python_bin)

        run_dir = RUNS_BASE / run_id
        if run_dir.exists():
            raise ValueError(f"run_id already exists: {run_dir}")
        run_dir.mkdir(parents=True, exist_ok=False)

        paths = build_paths(
            run_id=run_id,
            case_id=case_id,
            model_name=model_name,
            max_steps=max_steps,
            resume=resume,
            job_id=None,
        )

        emitter = Emitter(run_id, mirror_path=paths.events_path)
        emitter.emit("started", mode="slurm_summarize_agent", pid=os.getpid(), run_id=run_id)

        normalized_request = {
            "request_id": request_id,
            "case": case,
            "checklist": checklist_offsets,
            "checklist_definitions": checklist_definitions,
            "summary_constraints": summary_constraints,
            "model": model_name,
            "max_steps": max_steps,
            "reasoning_effort": reasoning_effort,
            "resume": resume,
            "debug": debug,
            "k_recent_tool_outputs": k_recent_tool_outputs,
            "prompt_config": prompt_config,
            "slurm": request.get("slurm") or {},
        }
        if focus_context is not None:
            normalized_request["focus_context"] = focus_context

        write_json(paths.request_path, normalized_request)

        emitter.emit(
            "request_validated",
            run_id=run_id,
            request_id=request_id,
            case_id=case_id,
            model=model_name,
            max_steps=max_steps,
            reasoning_effort=reasoning_effort,
            checklist_items_count=len(checklist_offsets),
            summary_constraints_count=len(summary_constraints),
            focus_context=focus_context,
            request_path=str(paths.request_path),
        )

        _, corpus_path = run_preprocess(
            emitter,
            case=case,
            model_name=model_name,
            paths=paths,
            python_bin=python_bin,
        )
        document_map = load_document_map(corpus_path)
        emitter.emit("document_map_ready", run_id=run_id, document_count=len(document_map.get("documents", [])))

        checklist_sentence_spans = convert_checklist_offsets_to_sentences(checklist_offsets, corpus_path)

        evidence_count = 0
        for item in checklist_sentence_spans.values():
            if not isinstance(item, dict):
                continue
            for ext in item.get("extracted", []):
                if isinstance(ext, dict):
                    evidence_count += len(ext.get("evidence") or [])

        agent_request = {
            "request_id": request_id,
            "run_id": run_id,
            "case_id": case_id,
            "checklist": checklist_sentence_spans,
            "checklist_definitions": checklist_definitions,
            "summary_constraints": summary_constraints,
        }
        if focus_context is not None:
            agent_request["focus_context"] = focus_context
        write_json(paths.agent_request_path, agent_request)

        emitter.emit(
            "checklist_prepared",
            run_id=run_id,
            checklist_items_count=len(checklist_sentence_spans),
            evidence_count=evidence_count,
            agent_request_path=str(paths.agent_request_path),
        )

        output_base_dir = f"controller/runs/{run_id}/agent_output"
        job_id = submit_slurm(
            request=normalized_request,
            case_id=case_id,
            model_name=model_name,
            max_steps=max_steps,
            reasoning_effort=reasoning_effort,
            resume=resume,
            debug=debug,
            output_base_dir=output_base_dir,
            data_dataset_name=paths.data_dataset_name,
            agent_request_path=paths.agent_request_path,
            k_recent_tool_outputs=k_recent_tool_outputs,
            prompt_config=prompt_config,
        )

        paths = build_paths(
            run_id=run_id,
            case_id=case_id,
            model_name=model_name,
            max_steps=max_steps,
            resume=resume,
            job_id=job_id,
        )

        emitter.emit(
            "slurm_submitted",
            run_id=run_id,
            job_id=job_id,
            sbatch_script=str(SBATCH_SCRIPT),
            output_dir=str(paths.output_dir),
            ledger_path=str(paths.ledger_path),
            slurm_log_path=str(paths.slurm_log_path) if paths.slurm_log_path else None,
        )

        poll_seconds = max(args.poll_seconds, 0.5)
        max_wait_seconds = max(args.max_wait_seconds, 10)
        start = time.monotonic()
        last_state = None

        if paths.ledger_path.exists():
            st = paths.ledger_path.stat()
            ledger_pos = st.st_size
            ledger_identity: Optional[Tuple[int, int]] = (st.st_dev, st.st_ino)
        else:
            ledger_pos = 0
            ledger_identity = None
        seen_steps: Set[int] = set()

        while True:
            state = slurm_state(job_id)
            if state != last_state:
                emitter.emit("slurm_state", run_id=run_id, job_id=job_id, state=state)
                last_state = state

            ledger_pos, ledger_identity = emit_new_steps(
                emitter,
                paths.ledger_path,
                ledger_pos,
                seen_steps,
                ledger_identity,
            )

            if state in TERMINAL_STATES:
                break

            if time.monotonic() - start > max_wait_seconds:
                run_cmd([slurm_executable("scancel"), job_id])
                emitter.emit(
                    "failed",
                    run_id=run_id,
                    error="Controller timed out waiting for SLURM job",
                    job_id=job_id,
                )
                return 3

            time.sleep(poll_seconds)

        artifact_bundle = build_artifact_bundle(
            run_id=run_id,
            request_id=request_id,
            case_id=case_id,
            job_id=job_id,
            state=state,
            paths=paths,
            request=normalized_request,
            checklist_offsets=checklist_offsets,
            checklist_sentence_spans=checklist_sentence_spans,
            document_map=document_map,
            corpus_path=corpus_path,
        )

        if state == "COMPLETED":
            emitter.emit("completed", job_id=job_id, state=state, **artifact_bundle)
            return 0

        emitter.emit("failed", job_id=job_id, state=state, **artifact_bundle)
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Controller for summary-agent SLURM runs")
    parser.add_argument(
        "--mode",
        choices=["smoke", "slurm_summarize_agent"],
        default="slurm_summarize_agent",
        help="Execution mode",
    )
    parser.add_argument("--request-id", default=None, help="Request ID for smoke mode")
    parser.add_argument("--ticks", type=int, default=5, help="Heartbeats in smoke mode")
    parser.add_argument("--tick-seconds", type=float, default=1.0, help="Heartbeat interval in smoke mode")
    parser.add_argument(
        "--fail-at",
        type=int,
        default=-1,
        help="Emit failed at this heartbeat index in smoke mode (-1 disables)",
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=2.0,
        help="Polling interval for SLURM job state",
    )
    parser.add_argument(
        "--max-wait-seconds",
        type=float,
        default=21600.0,
        help="Maximum controller wait time before cancelling the job",
    )
    parser.add_argument(
        "--python-bin",
        default=DEFAULT_PYTHON_BIN,
        help="Python path used for preprocessing (can also be provided as request.python_bin)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.mode == "smoke":
            return run_smoke(args)

        if args.mode == "slurm_summarize_agent":
            return run_slurm_summarize_agent(args)

        raise ValueError(f"Unsupported mode: {args.mode}")
    except KeyboardInterrupt:
        request_id = args.request_id or "unknown_request"
        emitter = Emitter(request_id)
        emitter.emit("failed", error="Interrupted by keyboard signal", exit_code=130)
        emitter.close()
        return 130
    except Exception as exc:
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
