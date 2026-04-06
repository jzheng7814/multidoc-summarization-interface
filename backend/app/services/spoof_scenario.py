from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from app.core.config import Settings, get_settings
from app.schemas.documents import Document
from app.schemas.runs import RunExtractionConfig, RunSummaryConfig
from app.services.spoof_replay import resolve_spoof_path


class SpoofScenario(BaseModel):
    title: str = Field(..., min_length=1)
    documents: List[Document] = Field(default_factory=list)
    extraction_config: RunExtractionConfig = Field(
        ...,
        serialization_alias="extractionConfig",
        validation_alias=AliasChoices("extractionConfig", "extraction_config"),
    )
    summary_config: RunSummaryConfig = Field(
        ...,
        serialization_alias="summaryConfig",
        validation_alias=AliasChoices("summaryConfig", "summary_config"),
    )

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def resolve_spoof_scenario_path(configured_path: str) -> Path:
    return resolve_spoof_path(configured_path)


def load_spoof_scenario(settings: Optional[Settings] = None) -> SpoofScenario:
    effective_settings = settings or get_settings()
    scenario_path = resolve_spoof_scenario_path(effective_settings.cluster_spoof_scenario_path)
    return _load_spoof_scenario_file(scenario_path)


def validate_spoof_scenario_path(configured_path: str) -> None:
    scenario_path = resolve_spoof_scenario_path(configured_path)
    if not scenario_path.exists():
        raise RuntimeError(f"Spoof scenario file not found: {scenario_path}")
    if not scenario_path.is_file():
        raise RuntimeError(f"Spoof scenario path is not a file: {scenario_path}")
    _load_spoof_scenario_file(scenario_path)


def _load_spoof_scenario_file(scenario_path: Path) -> SpoofScenario:
    try:
        payload = json.loads(scenario_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Spoof scenario file not found: {scenario_path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Spoof scenario JSON is invalid: {scenario_path}") from exc

    if not isinstance(payload, dict):
        raise RuntimeError(f"Spoof scenario file must decode to a JSON object: {scenario_path}")
    return SpoofScenario.model_validate(payload)
