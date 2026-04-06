from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from app.core.config import get_settings
from app.eventing import get_event_producer
from app.schemas.checklists import EvidenceCollection
from app.schemas.documents import Document
from app.schemas.summary import SummaryRequest
from app.services.remote_stage import RemoteStageManager
from app.services.spoof_replay import validate_spoof_fixture_dir
from app.services.spoof_scenario import validate_spoof_scenario_path
from app.services.summary_agent_payload import build_summary_agent_request_payload

producer = get_event_producer(__name__)
ProgressCallback = Callable[[str, Dict[str, Any]], None]


@dataclass(frozen=True)
class ClusterSummaryResult:
    summary_text: str
    run_id: str
    job_id: str
    completion_stats: Dict[str, Any]
    result_payload_path: str
    manifest_path: str
    summary_path: str


class ClusterSummaryRunner:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._stage_manager = RemoteStageManager(self._settings)

    async def run(
        self,
        backend_run_id: str,
        corpus_id: str,
        *,
        run_title: Optional[str],
        documents: Sequence[Document],
        checklist_collection: EvidenceCollection,
        checklist_definitions: Mapping[str, str],
        request: SummaryRequest,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> ClusterSummaryResult:
        if not documents:
            raise RuntimeError(f"No documents are available for corpus '{corpus_id}'.")
        if not checklist_definitions:
            raise RuntimeError("Checklist definitions are empty; cannot build summary-agent request.")

        request_id = f"summary_{corpus_id}_{uuid.uuid4().hex[:12]}"

        controller_request = build_summary_agent_request_payload(
            corpus_id=corpus_id,
            run_title=run_title,
            request_id=request_id,
            documents=documents,
            checklist_collection=checklist_collection,
            checklist_definitions=checklist_definitions,
            request=request,
            settings=self._settings,
        )
        stage_paths = await asyncio.to_thread(self._stage_manager.require_existing_stage, backend_run_id)
        process = await asyncio.create_subprocess_exec(
            "ssh",
            self._settings.cluster_ssh_host,
            self._stage_manager.build_remote_command(
                stage_paths,
                controller_script=self._settings.cluster_summary_remote_controller_script,
                mode="slurm_summarize_agent",
            ),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        if process.stdin is None or process.stdout is None or process.stderr is None:
            raise RuntimeError("Failed to open SSH pipes for summary controller process.")

        serialized_request = json.dumps(controller_request, ensure_ascii=True) + "\n"
        process.stdin.write(serialized_request.encode("utf-8"))
        await process.stdin.drain()
        process.stdin.close()

        stderr_task = asyncio.create_task(self._stream_stderr(corpus_id, request_id, process.stderr))
        terminal_event_type: Optional[str] = None
        terminal_data: Dict[str, Any] = {}

        try:
            while True:
                raw_line = await process.stdout.readline()
                if not raw_line:
                    break
                parsed = self._parse_controller_stdout_line(raw_line)
                if parsed is None:
                    continue

                event_type = parsed["event_type"]
                event_data = parsed["data"]
                self._emit_controller_event(corpus_id, request_id, parsed)

                if progress_callback is not None:
                    try:
                        progress_callback(event_type, dict(event_data))
                    except Exception as exc:  # pylint: disable=broad-except
                        producer.warning(
                            "Summary progress callback failed",
                            {"corpus_id": corpus_id, "request_id": request_id, "error": str(exc)},
                        )

                if event_type in {"completed", "failed"}:
                    terminal_event_type = event_type
                    terminal_data = event_data

            return_code = await process.wait()
            await stderr_task

            if terminal_event_type is None:
                raise RuntimeError(
                    "Summary controller exited without terminal event "
                    f"(exit_code={return_code}, request_id={request_id})."
                )

            if terminal_event_type == "failed":
                detail = self._failure_detail(terminal_data)
                raise RuntimeError(f"Summary controller reported failure: {detail}")

            if return_code != 0:
                raise RuntimeError(
                    "Summary controller exited non-zero after completed event "
                    f"(exit_code={return_code}, request_id={request_id})."
                )

            result = await asyncio.to_thread(self._result_from_completed_event, terminal_data, corpus_id)
            producer.info(
                "Summary controller run completed",
                {
                    "corpus_id": corpus_id,
                    "request_id": request_id,
                    "run_id": result.run_id,
                    "job_id": result.job_id,
                },
            )
            return result
        finally:
            if not stderr_task.done():
                stderr_task.cancel()
                try:
                    await stderr_task
                except asyncio.CancelledError:
                    pass

    async def _stream_stderr(self, corpus_id: str, request_id: str, stderr: asyncio.StreamReader) -> None:
        while True:
            line = await stderr.readline()
            if not line:
                break
            message = line.decode("utf-8", errors="replace").rstrip("\n")
            if not message:
                continue
            producer.warning(
                "Summary controller stderr",
                {"corpus_id": corpus_id, "request_id": request_id, "message": message},
            )

    def _parse_controller_stdout_line(self, raw_line: bytes) -> Optional[Dict[str, Any]]:
        text_line = raw_line.decode("utf-8", errors="replace").strip()
        if not text_line:
            return None

        try:
            payload = json.loads(text_line)
        except json.JSONDecodeError:
            producer.warning("Received non-JSON line from summary controller", {"line": text_line[:500]})
            return None

        if not isinstance(payload, dict):
            producer.warning("Received unexpected summary controller payload type", {"type": type(payload).__name__})
            return None

        event_type = payload.get("event_type")
        if not isinstance(event_type, str):
            producer.warning("Summary controller payload missing event_type", {"payload": text_line[:500]})
            return None

        data = payload.get("data")
        if not isinstance(data, dict):
            data = {}

        return {
            "event_type": event_type,
            "request_id": payload.get("request_id"),
            "seq": payload.get("seq"),
            "timestamp": payload.get("timestamp"),
            "data": data,
        }

    def _emit_controller_event(self, corpus_id: str, request_id: str, payload: Dict[str, Any]) -> None:
        event_type = payload["event_type"]
        event_data = payload["data"]
        log_payload = {
            "corpus_id": corpus_id,
            "request_id": request_id,
            "controller_request_id": payload.get("request_id"),
            "seq": payload.get("seq"),
            "event_type": event_type,
            "job_id": event_data.get("job_id"),
            "state": event_data.get("state"),
            "run_id": event_data.get("run_id"),
        }
        if event_type == "failed":
            producer.error("Summary controller event", log_payload)
            return
        producer.info("Summary controller event", log_payload)

    def _failure_detail(self, data: Dict[str, Any]) -> str:
        error = data.get("error")
        if isinstance(error, str) and error.strip():
            return error.strip()
        message = data.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
        state = data.get("state")
        if isinstance(state, str) and state.strip():
            return state.strip()
        return "unknown summary controller error"

    def _result_from_completed_event(self, completed_data: Dict[str, Any], corpus_id: str) -> ClusterSummaryResult:
        run_id = self._require_non_empty_string(completed_data.get("run_id"), "run_id")
        job_id = self._require_non_empty_string(completed_data.get("job_id"), "job_id")
        result_payload_path = PurePosixPath(
            self._require_non_empty_string(completed_data.get("result_payload_path"), "result_payload_path")
        )
        manifest_path = PurePosixPath(
            self._require_non_empty_string(completed_data.get("manifest_path"), "manifest_path")
        )
        summary_path = PurePosixPath(
            self._require_non_empty_string(completed_data.get("summary_path"), "summary_path")
        )

        with tempfile.TemporaryDirectory(prefix="cluster_summary_artifacts_") as temp_dir:
            temp_path = Path(temp_dir)
            local_result_payload = self._rsync_pull_file(result_payload_path, temp_path)
            local_summary = self._rsync_pull_file(summary_path, temp_path)

            result_payload = json.loads(local_result_payload.read_text(encoding="utf-8"))
            summary_payload = json.loads(local_summary.read_text(encoding="utf-8"))

            completion_stats = result_payload.get("completion_stats")
            if not isinstance(completion_stats, dict):
                completion_stats = {}

            summary_text = self._extract_summary_text(summary_payload, result_payload, corpus_id).strip()
            if not summary_text:
                raise RuntimeError(f"Summary output for corpus_id '{corpus_id}' was empty.")

            return ClusterSummaryResult(
                summary_text=summary_text,
                run_id=run_id,
                job_id=job_id,
                completion_stats=completion_stats,
                result_payload_path=str(result_payload_path),
                manifest_path=str(manifest_path),
                summary_path=str(summary_path),
            )

    def _extract_summary_text(self, summary_payload: Any, result_payload: Any, corpus_id: str) -> str:
        if isinstance(summary_payload, dict):
            summary_value = summary_payload.get("summary")
            if summary_value is not None:
                text = self._coerce_summary_text(summary_value).strip()
                if text:
                    return text

        if isinstance(result_payload, dict):
            summary_value = result_payload.get("summary")
            if summary_value is not None:
                text = self._coerce_summary_text(summary_value).strip()
                if text:
                    return text

        raise RuntimeError(
            f"Summary artifacts did not include a non-empty summary for corpus_id '{corpus_id}'. "
            "Expected 'summary_path' JSON field 'summary' or result_payload.summary."
        )

    def _coerce_summary_text(self, value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            for key in ("summary", "text", "content", "answer"):
                candidate = value.get(key)
                if isinstance(candidate, str):
                    return candidate
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    def _rsync_pull_file(self, remote_path: PurePosixPath, destination_dir: Path) -> Path:
        command = [
            "rsync",
            "-az",
            "--",
            f"{self._settings.cluster_ssh_host}:{str(remote_path)}",
            str(destination_dir),
        ]
        result = subprocess.run(command, check=False, text=True, capture_output=True)
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            stdout = (result.stdout or "").strip()
            detail = stderr or stdout or "unknown error"
            raise RuntimeError(f"Failed to pull remote artifact '{remote_path}': {detail}")

        local_path = destination_dir / remote_path.name
        if not local_path.exists():
            raise RuntimeError(f"Expected downloaded artifact was not found: '{local_path}'.")
        return local_path

    def _require_non_empty_string(self, value: Any, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(f"Summary controller payload missing '{field_name}'.")
        return value.strip()


_RUNNER = ClusterSummaryRunner()


def validate_cluster_summary_runtime_prerequisites() -> None:
    settings = get_settings()
    if settings.cluster_run_mode == "spoof":
        validate_spoof_scenario_path(settings.cluster_spoof_scenario_path)
        validate_spoof_fixture_dir(
            settings.cluster_spoof_summary_fixture_dir,
            label="Spoof summary",
            required_files=(
                "events.ndjson",
                "request.json",
                "manifest.json",
                "result_payload.json",
                "summary.json",
            ),
        )
        return

    config_errors: List[str] = []

    required_text_fields = {
        "MULTI_DOCUMENT_CLUSTER_SSH_HOST": settings.cluster_ssh_host,
        "MULTI_DOCUMENT_CLUSTER_REMOTE_STAGE_ROOT": settings.cluster_remote_stage_root,
        "MULTI_DOCUMENT_CLUSTER_REMOTE_PYTHON_PATH": settings.cluster_remote_python_path,
        "MULTI_DOCUMENT_CLUSTER_REMOTE_HF_CACHE_DIR": settings.cluster_remote_hf_cache_dir,
        "MULTI_DOCUMENT_CLUSTER_REMOTE_SLURM_BIN_DIR": settings.cluster_remote_slurm_bin_dir,
        "MULTI_DOCUMENT_CLUSTER_SUMMARY_REMOTE_CONTROLLER_SCRIPT": settings.cluster_summary_remote_controller_script,
    }
    for env_name, value in required_text_fields.items():
        if not isinstance(value, str) or not value.strip():
            config_errors.append(f"{env_name} must be set.")

    missing_binaries = [name for name in ("ssh", "rsync") if shutil.which(name) is None]
    for binary in missing_binaries:
        config_errors.append(f"Required local binary '{binary}' was not found on PATH.")

    if not settings.cluster_summary_remote_controller_script.startswith("interface_agents/"):
        config_errors.append(
            "MULTI_DOCUMENT_CLUSTER_SUMMARY_REMOTE_CONTROLLER_SCRIPT must be a path under interface_agents/."
        )

    try:
        RemoteStageManager(settings).validate_local_prerequisites()
    except RuntimeError as exc:
        config_errors.append(str(exc))

    if config_errors:
        joined = " ".join(config_errors)
        raise RuntimeError(f"Cluster summary prerequisites are not satisfied. {joined}")


async def run_cluster_summary(
    backend_run_id: str,
    corpus_id: str,
    *,
    run_title: Optional[str],
    documents: Sequence[Document],
    checklist_collection: EvidenceCollection,
    checklist_definitions: Mapping[str, str],
    request: SummaryRequest,
    progress_callback: Optional[ProgressCallback] = None,
) -> ClusterSummaryResult:
    return await _RUNNER.run(
        backend_run_id,
        corpus_id,
        run_title=run_title,
        documents=documents,
        checklist_collection=checklist_collection,
        checklist_definitions=checklist_definitions,
        request=request,
        progress_callback=progress_callback,
    )
