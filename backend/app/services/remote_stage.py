from __future__ import annotations

import json
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, Optional

from app.core.config import Settings, get_settings
from app.eventing import get_event_producer

producer = get_event_producer(__name__)

_RSYNC_EXCLUDES = (
    ".env",
    "agent_logs/",
    "data/",
    "controller/runs/",
    "controller/requests/",
    "__pycache__/",
    ".pytest_cache/",
)


@dataclass(frozen=True)
class RemoteStagePaths:
    stage_root: PurePosixPath
    run_dir: PurePosixPath
    interface_agents_dir: PurePosixPath
    checklist_base_dir: PurePosixPath
    summary_base_dir: PurePosixPath
    checklist_env_path: PurePosixPath
    summary_env_path: PurePosixPath
    manifest_path: PurePosixPath


def build_remote_stage_paths(stage_root: str, backend_run_id: str) -> RemoteStagePaths:
    root = PurePosixPath(stage_root)
    run_dir = root / backend_run_id
    interface_agents_dir = run_dir / "interface_agents"
    checklist_base_dir = interface_agents_dir / "checklist_agent"
    summary_base_dir = interface_agents_dir / "summary_agent"
    return RemoteStagePaths(
        stage_root=root,
        run_dir=run_dir,
        interface_agents_dir=interface_agents_dir,
        checklist_base_dir=checklist_base_dir,
        summary_base_dir=summary_base_dir,
        checklist_env_path=checklist_base_dir / ".env",
        summary_env_path=summary_base_dir / ".env",
        manifest_path=run_dir / "stage_manifest.json",
    )


class RemoteStageManager:
    def __init__(self, settings: Optional[Settings] = None) -> None:
        self._settings = settings or get_settings()
        self._repo_root = Path(__file__).resolve().parents[3]
        self._local_interface_agents_dir = self._repo_root / "interface_agents"

    @property
    def local_interface_agents_dir(self) -> Path:
        return self._local_interface_agents_dir

    def validate_local_prerequisites(self) -> None:
        if not self._local_interface_agents_dir.exists():
            raise RuntimeError(
                f"Required local interface_agents directory is missing: '{self._local_interface_agents_dir}'."
            )
        required_paths = (
            self._local_interface_agents_dir / "requirements.txt",
            self._local_interface_agents_dir / "checklist_agent" / "controller" / "run_controller.py",
            self._local_interface_agents_dir / "checklist_agent" / "controller" / "run_controller_native.py",
            self._local_interface_agents_dir / "summary_agent" / "controller" / "run_controller.py",
        )
        missing = [str(path) for path in required_paths if not path.exists()]
        if missing:
            raise RuntimeError(
                "Local interface_agents tree is incomplete. Missing required paths: "
                + ", ".join(missing)
            )

    def prepare_stage(self, backend_run_id: str) -> RemoteStagePaths:
        self.validate_local_prerequisites()
        stage_root = self._resolve_remote_stage_root()
        paths = build_remote_stage_paths(stage_root, backend_run_id)

        self._run_remote_command(
            "mkdir -p "
            f"{self._double_quote(str(paths.run_dir))} "
            f"{self._double_quote(str(paths.interface_agents_dir))}"
        )
        self._rsync_interface_agents(paths)
        self._rsync_overlay(paths, backend_run_id)
        producer.info(
            "Prepared remote interface_agents stage",
            {
                "backend_run_id": backend_run_id,
                "stage_root": str(paths.stage_root),
                "run_dir": str(paths.run_dir),
            },
        )
        return paths

    def require_existing_stage(self, backend_run_id: str) -> RemoteStagePaths:
        stage_root = self._resolve_remote_stage_root()
        paths = build_remote_stage_paths(stage_root, backend_run_id)
        self._run_remote_command(
            "test -d "
            f"{self._double_quote(str(paths.checklist_base_dir))} "
            "&& test -d "
            f"{self._double_quote(str(paths.summary_base_dir))}"
        )
        return paths

    def build_remote_command(
        self,
        stage_paths: RemoteStagePaths,
        *,
        controller_script: str,
        mode: str,
    ) -> str:
        inner_command = (
            f"cd {self._double_quote(str(stage_paths.run_dir))} && "
            f"{self._double_quote(self._settings.cluster_remote_python_path)} "
            f"{self._double_quote(controller_script)} "
            f"--mode {mode} "
            f"--poll-seconds {int(self._settings.cluster_poll_seconds)} "
            f"--max-wait-seconds {int(self._settings.cluster_max_wait_seconds)}"
        )
        return f"bash -lc {shlex.quote(inner_command)}"

    def _resolve_remote_stage_root(self) -> str:
        output = self._run_remote_command(
            "mkdir -p "
            f"{self._double_quote(self._settings.cluster_remote_stage_root)}"
            " && cd "
            f"{self._double_quote(self._settings.cluster_remote_stage_root)}"
            " && pwd"
        )
        resolved = [line.strip() for line in output.splitlines() if line.strip()]
        if not resolved:
            raise RuntimeError("Unable to resolve remote stage root: empty output.")
        return resolved[-1]

    def _rsync_interface_agents(self, paths: RemoteStagePaths) -> None:
        command = [
            "rsync",
            "-az",
            "--delete",
            *self._rsync_excludes(),
            f"{self._local_interface_agents_dir}/",
            f"{self._settings.cluster_ssh_host}:{str(paths.interface_agents_dir)}/",
        ]
        self._run_local_command(command, error_prefix="Failed to sync interface_agents to remote stage")

    def _rsync_overlay(self, paths: RemoteStagePaths, backend_run_id: str) -> None:
        with tempfile.TemporaryDirectory(prefix="interface_agents_stage_overlay_") as temp_dir:
            overlay_root = Path(temp_dir)
            checklist_env = overlay_root / "interface_agents" / "checklist_agent" / ".env"
            summary_env = overlay_root / "interface_agents" / "summary_agent" / ".env"
            checklist_env.parent.mkdir(parents=True, exist_ok=True)
            summary_env.parent.mkdir(parents=True, exist_ok=True)

            checklist_env.write_text(self._render_checklist_env(paths), encoding="utf-8")
            summary_env.write_text(self._render_summary_env(paths), encoding="utf-8")
            (overlay_root / "stage_manifest.json").write_text(
                json.dumps(self._build_manifest(paths, backend_run_id), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            command = [
                "rsync",
                "-az",
                f"{overlay_root}/",
                f"{self._settings.cluster_ssh_host}:{str(paths.run_dir)}/",
            ]
            self._run_local_command(command, error_prefix="Failed to sync stage overlay to remote stage")

    def _build_manifest(self, paths: RemoteStagePaths, backend_run_id: str) -> Dict[str, object]:
        git_commit = self._git_output(["git", "rev-parse", "HEAD"])
        git_dirty = bool(self._git_output(["git", "status", "--short"]))
        return {
            "backend_run_id": backend_run_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "stage_root": str(paths.stage_root),
            "run_dir": str(paths.run_dir),
            "controller_scripts": {
                "checklist": self._settings.cluster_remote_controller_script,
                "summary": self._settings.cluster_summary_remote_controller_script,
            },
            "remote_python_path": self._settings.cluster_remote_python_path,
            "remote_hf_cache_dir": self._settings.cluster_remote_hf_cache_dir,
            "local_git_commit": git_commit,
            "local_git_dirty": git_dirty,
            "local_repo_root": str(self._repo_root),
        }

    def _render_checklist_env(self, paths: RemoteStagePaths) -> str:
        values = {
            "INTERFACE_AGENT_BASE_DIR": str(paths.checklist_base_dir),
            "INTERFACE_AGENT_PYTHON_BIN": self._settings.cluster_remote_python_path,
            "INTERFACE_AGENT_SLURM_BIN_DIR": self._settings.cluster_remote_slurm_bin_dir,
            "INTERFACE_AGENT_HF_HOME": self._settings.cluster_remote_hf_cache_dir,
            "INTERFACE_AGENT_HUGGINGFACE_HUB_CACHE": f"{self._settings.cluster_remote_hf_cache_dir}/hub",
            "INTERFACE_AGENT_TRANSFORMERS_CACHE": f"{self._settings.cluster_remote_hf_cache_dir}/hub",
            "INTERFACE_AGENT_RUNS_BASE": str(paths.checklist_base_dir / "controller" / "runs"),
        }
        return self._render_env_lines(
            "# Generated by backend remote-stage sync.",
            values,
        )

    def _render_summary_env(self, paths: RemoteStagePaths) -> str:
        values = {
            "INTERFACE_SUMMARY_AGENT_BASE_DIR": str(paths.summary_base_dir),
            "INTERFACE_SUMMARY_AGENT_EXTRACTION_BASE_DIR": str(paths.checklist_base_dir),
            "INTERFACE_CHECKLIST_AGENT_BASE_DIR": str(paths.checklist_base_dir),
            "INTERFACE_SUMMARY_AGENT_PYTHON_BIN": self._settings.cluster_remote_python_path,
            "INTERFACE_SUMMARY_AGENT_SLURM_BIN_DIR": self._settings.cluster_remote_slurm_bin_dir,
            "INTERFACE_SUMMARY_AGENT_HF_HOME": self._settings.cluster_remote_hf_cache_dir,
            "INTERFACE_SUMMARY_AGENT_HUGGINGFACE_HUB_CACHE": f"{self._settings.cluster_remote_hf_cache_dir}/hub",
            "INTERFACE_SUMMARY_AGENT_TRANSFORMERS_CACHE": f"{self._settings.cluster_remote_hf_cache_dir}/hub",
            "INTERFACE_SUMMARY_AGENT_RUNS_BASE": str(paths.summary_base_dir / "controller" / "runs"),
        }
        return self._render_env_lines(
            "# Generated by backend remote-stage sync.",
            values,
        )

    def _render_env_lines(self, header: str, values: Dict[str, str]) -> str:
        lines = [header]
        lines.extend(f"{key}={value}" for key, value in values.items())
        return "\n".join(lines) + "\n"

    def _rsync_excludes(self) -> Iterable[str]:
        for pattern in _RSYNC_EXCLUDES:
            yield f"--exclude={pattern}"

    def _git_output(self, command: list[str]) -> Optional[str]:
        result = subprocess.run(
            command,
            cwd=self._repo_root,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None
        text = (result.stdout or "").strip()
        return text or None

    def _run_remote_command(self, inner_command: str) -> str:
        command = [
            "ssh",
            self._settings.cluster_ssh_host,
            f"bash -lc {shlex.quote(inner_command)}",
        ]
        return self._run_local_command(command, error_prefix="Remote stage command failed")

    def _run_local_command(self, command: list[str], *, error_prefix: str) -> str:
        result = subprocess.run(command, check=False, capture_output=True, text=True)
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            stdout = (result.stdout or "").strip()
            detail = stderr or stdout or "unknown error"
            raise RuntimeError(f"{error_prefix}: {detail}")
        return result.stdout or ""

    def _double_quote(self, value: str) -> str:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

