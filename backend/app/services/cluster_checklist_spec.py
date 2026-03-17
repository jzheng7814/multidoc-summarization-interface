from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Literal, Set


ChecklistStrategy = Literal["all", "individual"]


def load_cluster_checklist_spec(raw_path: str, strategy: ChecklistStrategy) -> Dict[str, Any]:
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

    if strategy == "all":
        return _validate_all_spec(payload, path)
    return _validate_individual_spec(payload, path)


def _resolve_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    backend_root = Path(__file__).resolve().parents[2]
    return backend_root / path


def _validate_all_spec(payload: Dict[str, Any], path: Path) -> Dict[str, Any]:
    if "user_instruction" not in payload:
        raise RuntimeError(
            f"Checklist spec missing required field for strategy=all: user_instruction ({path})."
        )
    if "constraints" not in payload:
        raise RuntimeError(f"Checklist spec missing required field for strategy=all: constraints ({path}).")

    normalized_items = _validate_common_items(payload, require_per_item_directives=False, path=path)
    return {
        "user_instruction": _require_non_empty_string(payload.get("user_instruction"), "user_instruction", path),
        "constraints": _require_constraints(payload.get("constraints"), "constraints", path),
        "checklist_items": normalized_items,
    }


def _validate_individual_spec(payload: Dict[str, Any], path: Path) -> Dict[str, Any]:
    if "user_instruction" in payload:
        raise RuntimeError(
            "Checklist spec for strategy=individual must not include top-level user_instruction "
            f"(file: {path})."
        )
    if "constraints" in payload:
        raise RuntimeError(
            "Checklist spec for strategy=individual must not include top-level constraints "
            f"(file: {path})."
        )

    normalized_items = _validate_common_items(payload, require_per_item_directives=True, path=path)
    return {"checklist_items": normalized_items}


def _validate_common_items(
    payload: Dict[str, Any], *, require_per_item_directives: bool, path: Path
) -> List[Dict[str, Any]]:
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

        item: Dict[str, Any] = {
            "key": key,
            "description": _require_non_empty_string(raw_item.get("description"), f"{field}.description", path),
        }

        if require_per_item_directives:
            item["user_instruction"] = _require_non_empty_string(
                raw_item.get("user_instruction"),
                f"{field}.user_instruction",
                path,
            )
            item["constraints"] = _require_constraints(
                raw_item.get("constraints"),
                f"{field}.constraints",
                path,
            )
            item["max_steps"] = _require_positive_int(
                raw_item.get("max_steps"),
                f"{field}.max_steps",
                path,
            )
            item["reasoning_effort"] = _require_reasoning_effort(
                raw_item.get("reasoning_effort"),
                f"{field}.reasoning_effort",
                path,
            )
        else:
            if "user_instruction" in raw_item:
                raise RuntimeError(
                    f"{field}.user_instruction is not allowed for strategy=all in checklist spec file: {path}"
                )
            if "constraints" in raw_item:
                raise RuntimeError(
                    f"{field}.constraints is not allowed for strategy=all in checklist spec file: {path}"
                )

        normalized_items.append(item)

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
