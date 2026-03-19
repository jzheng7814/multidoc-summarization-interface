from __future__ import annotations

import re
from pathlib import Path
from typing import Mapping, Optional

from app.core.config import Settings, get_settings

_PLACEHOLDER_PATTERN = re.compile(r"#([A-Z][A-Z0-9_]*)")


def load_cluster_focus_context(case_title: Optional[str], settings: Optional[Settings] = None) -> str:
    template = load_cluster_focus_context_template(settings)
    values = {
        "CASE_TITLE": str(case_title).strip() if isinstance(case_title, str) else "",
    }
    return render_cluster_focus_context_template(template, values)


def render_cluster_focus_context_template(template: str, values: Mapping[str, str]) -> str:
    if not isinstance(template, str):
        raise RuntimeError("Checklist focus context template must be a string.")

    cleaned_template = template.strip()
    if not cleaned_template:
        raise RuntimeError("Checklist focus context must not be empty.")

    missing: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        value = values.get(key)
        if not isinstance(value, str) or not value.strip():
            missing.append(key)
            return match.group(0)
        return value.strip()

    rendered = _PLACEHOLDER_PATTERN.sub(_replace, cleaned_template).strip()
    if missing:
        placeholders = ", ".join(sorted({f"#{key}" for key in missing}))
        raise RuntimeError(f"Missing runtime values for checklist focus context placeholders: {placeholders}")
    if not rendered:
        raise RuntimeError("Checklist focus context resolved to an empty string.")

    return rendered


def load_cluster_focus_context_template(settings: Optional[Settings] = None) -> str:
    resolved_settings = settings or get_settings()
    path = _resolve_focus_context_path(resolved_settings.cluster_focus_context_template_path)
    if not path.exists():
        raise RuntimeError(f"Checklist focus context template file not found: {path}")
    if not path.is_file():
        raise RuntimeError(f"Checklist focus context template path is not a file: {path}")

    return path.read_text(encoding="utf-8")


def _resolve_focus_context_path(configured_path: str) -> Path:
    path = Path(str(configured_path).strip())
    if path.is_absolute():
        return path
    backend_root = Path(__file__).resolve().parents[2]
    return (backend_root / path).resolve()
