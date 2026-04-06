from __future__ import annotations

import json
import os
from functools import cached_property, lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelDefaults(BaseModel):
    temperature: float = 0.3
    max_output_tokens: int = 4096
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class OpenAIModelConfig(BaseModel):
    response_model: str
    conversation_model: Optional[str] = None
    reasoning_effort: str
    api_key: Optional[str] = None
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    def conversation_model_name(self) -> str:
        return self.conversation_model or self.response_model


class OllamaModelConfig(BaseModel):
    base_url: str
    timeout_seconds: float = 60.0
    response_model: str
    conversation_model: Optional[str] = None
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    def conversation_model_name(self) -> str:
        return self.conversation_model or self.response_model


class ModelConfig(BaseModel):
    provider: Literal["openai", "ollama", "mock"] = "openai"
    defaults: ModelDefaults = Field(default_factory=ModelDefaults)
    openai: Optional[OpenAIModelConfig] = None
    ollama: Optional[OllamaModelConfig] = None
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class AppRuntimeConfig(BaseModel):
    event_log_dir: str = "logs"
    event_log_prefix: str = "events"
    ipc_socket_path: str = "/tmp/gavel_tool.sock"
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class AppConfig(BaseModel):
    model: ModelConfig
    app: AppRuntimeConfig = Field(default_factory=AppRuntimeConfig)
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Settings(BaseSettings):
    app_name: str = "multi-document-backend"
    environment: str = "development"
    use_mock_llm: bool = False
    config_path: str = "config/app.config.json"
    database_url: str
    openai_api_key: Optional[str] = None
    checklist_start_enabled: bool = True
    cluster_run_mode: Literal["remote", "spoof"] = "remote"
    cluster_spoof_event_delay_seconds: float = 0.0
    cluster_spoof_extraction_fixture_dir: str = (
        "../scratch/handoff/spoof_fixtures/extraction/run_20260317T222144Z_124c78addb"
    )
    cluster_spoof_summary_fixture_dir: str = (
        "../scratch/handoff/spoof_fixtures/summary/run_20260319T025055Z_6dcb90725b"
    )
    cluster_ssh_host: str = "sky1"
    cluster_remote_stage_root: str = "/coc/pskynet6/$USER/flash/interface_agent_runs"
    cluster_remote_python_path: str = "/coc/pskynet6/$USER/flash/miniconda3/envs/gavel-dev/bin/python"
    cluster_remote_hf_cache_dir: str = "/coc/pskynet6/$USER/flash/hf_cache"
    cluster_remote_slurm_bin_dir: str = "/opt/slurm/Ubuntu-20.04/current/bin"
    cluster_remote_controller_script: str = "interface_agents/checklist_agent/controller/run_controller_native.py"
    cluster_poll_seconds: int = 2
    cluster_max_wait_seconds: int = 21600
    cluster_model_name: str = "unsloth/gpt-oss-20b-BF16"
    cluster_checklist_strategy: Literal["all", "individual"] = "individual"
    cluster_checklist_spec_path: str = "app/resources/checklists/remote_checklist_spec.individual.json"
    cluster_focus_context_template_path: str = "app/resources/checklists/focus_context.template.txt"
    cluster_max_steps: int = 300
    cluster_resume: bool = False
    cluster_debug: bool = False
    cluster_output_base_dir: str = "output_controller"
    cluster_dataset_prefix: str = "controller"
    cluster_slurm_partition: str = "nlprx-lab"
    cluster_slurm_qos: str = "short"
    cluster_summary_remote_controller_script: str = "interface_agents/summary_agent/controller/run_controller.py"
    cluster_summary_model_name: str = "unsloth/gpt-oss-20b-BF16"
    cluster_summary_max_steps: int = 200
    cluster_summary_reasoning_effort: Literal["low", "medium", "high"] = "medium"
    cluster_summary_k_recent_tool_outputs: int = 5
    cluster_summary_prompt_config: Optional[str] = None
    cluster_summary_focus_context_template_path: str = "app/resources/summary/focus_context.template.txt"
    cluster_summary_slurm_partition: str = "nlprx-lab"
    cluster_summary_slurm_qos: str = "short"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="MULTI_DOCUMENT_",
        extra="ignore",
    )

    @cached_property
    def app_config(self) -> AppConfig:
        config_path = Path(self.config_path)
        if not config_path.is_absolute():
            backend_root = Path(__file__).resolve().parents[2]
            config_path = backend_root / config_path
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
            return AppConfig.model_validate(raw)
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise RuntimeError(f"Failed to load configuration from {config_path}: {exc}") from exc

    @property
    def model(self) -> ModelConfig:
        return self.app_config.model

    @property
    def app(self) -> AppRuntimeConfig:
        return self.app_config.app

    def resolve_openai_api_key(self) -> Optional[str]:
        configured = self.openai_api_key or (self.model.openai.api_key if self.model.openai else None)
        return configured or os.getenv("OPENAI_API_KEY")


@lru_cache
def get_settings() -> Settings:
    return Settings()
