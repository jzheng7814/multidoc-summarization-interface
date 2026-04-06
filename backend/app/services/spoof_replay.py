from __future__ import annotations

import asyncio
from collections import Counter
import json
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

ProgressCallback = Callable[[str, Dict[str, Any]], None]


def resolve_spoof_fixture_dir(configured_path: str) -> Path:
    path = Path(str(configured_path).strip())
    if path.is_absolute():
        return path
    backend_root = Path(__file__).resolve().parents[2]
    return (backend_root / path).resolve()


def validate_spoof_fixture_dir(configured_path: str, *, label: str, required_files: Sequence[str]) -> None:
    fixture_dir = resolve_spoof_fixture_dir(configured_path)
    if not fixture_dir.exists():
        raise RuntimeError(f"{label} fixture directory not found: {fixture_dir}")
    if not fixture_dir.is_dir():
        raise RuntimeError(f"{label} fixture path is not a directory: {fixture_dir}")

    missing = [name for name in required_files if not (fixture_dir / name).exists()]
    if missing:
        formatted = ", ".join(sorted(missing))
        raise RuntimeError(f"{label} fixture directory is missing required files: {formatted}")


def load_spoof_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Spoof fixture JSON is invalid: {path}") from exc


def load_spoof_events(events_path: Path) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for line_number, line in enumerate(events_path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid NDJSON in spoof fixture {events_path} at line {line_number}.") from exc
        if not isinstance(payload, dict):
            raise RuntimeError(f"Spoof fixture event line {line_number} must decode to an object: {events_path}")
        event_type = payload.get("event_type")
        if not isinstance(event_type, str) or not event_type.strip():
            raise RuntimeError(f"Spoof fixture event line {line_number} is missing event_type: {events_path}")
        data = payload.get("data")
        if data is not None and not isinstance(data, dict):
            raise RuntimeError(f"Spoof fixture event line {line_number} has non-object data: {events_path}")
        events.append(payload)

    if not events:
        raise RuntimeError(f"Spoof fixture did not contain any events: {events_path}")
    return events


def get_terminal_spoof_event(events: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    for payload in reversed(list(events)):
        event_type = payload.get("event_type")
        if event_type in {"completed", "failed"}:
            return dict(payload)
    raise RuntimeError("Spoof fixture did not contain a terminal completed/failed event.")


def require_completed_terminal_event(terminal_event: Mapping[str, Any], *, label: str) -> None:
    event_type = terminal_event.get("event_type")
    if event_type != "completed":
        raise RuntimeError(f"{label} terminal event must be 'completed'. Got '{event_type}'.")

    data = terminal_event.get("data")
    state = ""
    if isinstance(data, dict):
        raw_state = data.get("state")
        if isinstance(raw_state, str):
            state = raw_state.strip().upper()
    if state and state != "COMPLETED":
        raise RuntimeError(f"{label} terminal state must be COMPLETED. Got '{state}'.")


def load_spoof_request_payload(fixture_dir: Path) -> Dict[str, Any]:
    payload = load_spoof_json(fixture_dir / "request.json")
    if not isinstance(payload, dict):
        raise RuntimeError(f"Spoof fixture request.json must be a JSON object: {fixture_dir}")
    return payload


def validate_fixture_corpus(corpus_id: str, request_payload: Mapping[str, Any], *, label: str) -> None:
    input_payload = request_payload.get("input")
    if not isinstance(input_payload, dict):
        raise RuntimeError(f"{label} request payload is missing input object.")
    fixture_corpus_id = str(input_payload.get("corpus_id") or "").strip()
    if not fixture_corpus_id:
        raise RuntimeError(f"{label} request payload is missing input.corpus_id.")
    if fixture_corpus_id != str(corpus_id).strip():
        raise RuntimeError(
            f"{label} corpus_id mismatch. Requested '{corpus_id}', fixture contains '{fixture_corpus_id}'."
        )


def validate_fixture_document_ids(
    document_ids: Sequence[Any],
    request_payload: Mapping[str, Any],
    *,
    label: str,
) -> None:
    input_payload = request_payload.get("input")
    if not isinstance(input_payload, dict):
        raise RuntimeError(f"{label} request payload is missing input object.")

    raw_documents = input_payload.get("documents")
    if not isinstance(raw_documents, list) or not raw_documents:
        raise RuntimeError(f"{label} request payload is missing input.documents.")

    fixture_ids = []
    for index, entry in enumerate(raw_documents):
        if not isinstance(entry, dict):
            raise RuntimeError(f"{label} input.documents[{index}] must be an object.")
        document_id = str(entry.get("document_id") or "").strip()
        if not document_id:
            raise RuntimeError(f"{label} input.documents[{index}] is missing document_id.")
        fixture_ids.append(document_id)
    current_ids = [str(value).strip() for value in document_ids]
    if Counter(fixture_ids) != Counter(current_ids):
        raise RuntimeError(
            f"{label} document ids do not match fixture payload. "
            f"requested={current_ids}, fixture={fixture_ids}"
        )


async def replay_spoof_events(
    events: Sequence[Mapping[str, Any]],
    *,
    progress_callback: Optional[ProgressCallback],
    delay_seconds: float,
) -> Dict[str, Any]:
    terminal_event: Optional[Dict[str, Any]] = None
    for index, payload in enumerate(events):
        event_type = str(payload.get("event_type") or "").strip()
        data = payload.get("data")
        event_data = dict(data) if isinstance(data, dict) else {}

        if progress_callback is not None:
            progress_callback(event_type, event_data)

        if event_type in {"completed", "failed"}:
            terminal_event = dict(payload)

        if delay_seconds > 0 and index < len(events) - 1:
            await asyncio.sleep(delay_seconds)

    if terminal_event is None:
        raise RuntimeError("Spoof replay did not encounter a terminal event.")
    return terminal_event
