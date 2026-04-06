from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Set


def load_cluster_checklist_spec(raw_path: str) -> Dict[str, Any]:
    path = _resolve_path(raw_path)
    if not path.exists():
        raise RuntimeError(f"Checklist spec file not found: {path}")
    if not path.is_file():
        raise RuntimeError(f"Checklist spec path is not a file: {path}")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Checklist spec file is not valid JSON: {path}") from exc

    if not isinstance(payload, dict):
        raise RuntimeError("Checklist spec file root must be a JSON object.")

    return validate_cluster_checklist_spec_payload(payload, path=path)


def validate_cluster_checklist_spec_payload(payload: Dict[str, Any], path: Path | None = None) -> Dict[str, Any]:
    effective_path = path or Path("<inline-checklist-spec>")

    if "user_instruction" in payload:
        raise RuntimeError(
            "Checklist spec must not include top-level user_instruction "
            f"(file: {effective_path})."
        )
    if "constraints" in payload:
        raise RuntimeError(
            "Checklist spec must not include top-level constraints "
            f"(file: {effective_path})."
        )

    normalized_items = _validate_items(payload, path=effective_path)
    return {"checklist_items": normalized_items}


def _resolve_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    backend_root = Path(__file__).resolve().parents[2]
    return backend_root / path


def _validate_items(payload: Dict[str, Any], *, path: Path) -> List[Dict[str, Any]]:
    raw_items = payload.get("checklist_items")
    if not isinstance(raw_items, list):
        raise RuntimeError(f"`checklist_items` must be an array in checklist spec file: {path}")
    if not raw_items:
        raise RuntimeError(f"`checklist_items` must contain at least one item in checklist spec file: {path}")

    keys_seen: Set[str] = set()
    normalized_items: List[Dict[str, Any]] = []
    for idx, raw_item in enumerate(raw_items):
        field = f"checklist_items[{idx}]"
        if not isinstance(raw_item, dict):
            raise RuntimeError(f"{field} must be an object in checklist spec file: {path}")

        key = _require_non_empty_string(raw_item.get("key"), f"{field}.key", path)
        if key in keys_seen:
            raise RuntimeError(f"Duplicate checklist key `{key}` in checklist spec file: {path}")
        keys_seen.add(key)

        normalized_items.append(
            {
                "key": key,
                "description": _require_non_empty_string(raw_item.get("description"), f"{field}.description", path),
                "user_instruction": _require_non_empty_string(
                    raw_item.get("user_instruction"),
                    f"{field}.user_instruction",
                    path,
                ),
                "constraints": _require_constraints(
                    raw_item.get("constraints"),
                    f"{field}.constraints",
                    path,
                ),
                "max_steps": _require_positive_int(
                    raw_item.get("max_steps"),
                    f"{field}.max_steps",
                    path,
                ),
                "reasoning_effort": _require_reasoning_effort(
                    raw_item.get("reasoning_effort"),
                    f"{field}.reasoning_effort",
                    path,
                ),
            }
        )

    return normalized_items


def _require_non_empty_string(value: Any, field_name: str, path: Path) -> str:
    if not isinstance(value, str):
        raise RuntimeError(f"{field_name} must be a string in checklist spec file: {path}")
    cleaned = value.strip()
    if not cleaned:
        raise RuntimeError(f"{field_name} must not be empty in checklist spec file: {path}")
    return cleaned


def _require_constraints(value: Any, field_name: str, path: Path) -> List[str]:
    if not isinstance(value, list):
        raise RuntimeError(f"{field_name} must be a list in checklist spec file: {path}")

    constraints: List[str] = []
    for idx, entry in enumerate(value):
        if not isinstance(entry, str):
            raise RuntimeError(f"{field_name}[{idx}] must be a string in checklist spec file: {path}")
        cleaned = entry.strip()
        if not cleaned:
            raise RuntimeError(f"{field_name}[{idx}] must not be empty in checklist spec file: {path}")
        constraints.append(cleaned)
    return constraints


def _require_positive_int(value: Any, field_name: str, path: Path) -> int:
    if not isinstance(value, int):
        raise RuntimeError(f"{field_name} must be an integer in checklist spec file: {path}")
    if value < 1:
        raise RuntimeError(f"{field_name} must be >= 1 in checklist spec file: {path}")
    return value


def _require_reasoning_effort(value: Any, field_name: str, path: Path) -> str:
    if not isinstance(value, str):
        raise RuntimeError(f"{field_name} must be a string in checklist spec file: {path}")
    cleaned = value.strip().lower()
    if cleaned not in {"low", "medium", "high"}:
        raise RuntimeError(
            f"{field_name} must be one of ['low', 'medium', 'high'] in checklist spec file: {path}"
        )
    return cleaned
