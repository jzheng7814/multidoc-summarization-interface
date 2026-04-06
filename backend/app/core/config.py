from __future__ import annotations

from functools import lru_cache
from typing import Literal, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "multi-document-backend"
    environment: str = "development"
    database_url: str

    event_log_dir: str = "logs"
    event_log_prefix: str = "events"
    ipc_socket_path: str = "/tmp/gavel_tool.sock"

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
    cluster_checklist_spec_path: str = "app/resources/checklists/remote_checklist_spec.individual.json"
    cluster_focus_context_template_path: str = "app/resources/checklists/focus_context.template.txt"
    cluster_resume: bool = False
    cluster_debug: bool = False
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
