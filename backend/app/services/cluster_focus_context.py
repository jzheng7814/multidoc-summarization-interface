from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml


def load_cluster_focus_context() -> str:
    path = _focus_context_path()
    if not path.exists():
        raise RuntimeError(f"Focus context file not found: {path}")
    if not path.is_file():
        raise RuntimeError(f"Focus context path is not a file: {path}")

    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise RuntimeError(f"Focus context file is not valid YAML: {path}") from exc

    if not isinstance(payload, dict):
        raise RuntimeError(f"Focus context file root must be a mapping: {path}")

    value = payload.get("focus_context")
    if not isinstance(value, str):
        raise RuntimeError(f"`focus_context` must be a string in focus context file: {path}")

    cleaned = value.strip()
    if not cleaned:
        raise RuntimeError(f"`focus_context` must not be empty in focus context file: {path}")

    return cleaned


def _focus_context_path() -> Path:
    backend_root = Path(__file__).resolve().parents[2]
    return backend_root / "app/resources/checklists/focus_context.yaml"
