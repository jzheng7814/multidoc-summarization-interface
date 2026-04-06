from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from app.core.config import get_settings
from app.eventing import get_event_producer
from app.schemas.checklists import SUMMARY_DOCUMENT_ID, EvidenceCollection, EvidenceItem, EvidencePointer
from app.schemas.documents import DocumentReference
from app.services.cluster_checklist_spec import load_cluster_checklist_spec
from app.services.cluster_focus_context import load_cluster_focus_context
from app.services.remote_stage import RemoteStageManager
from app.services.spoof_replay import validate_spoof_fixture_dir

producer = get_event_producer(__name__)
ProgressCallback = Callable[[str, Dict[str, Any]], None]


@dataclass(frozen=True)
class ResolvedClusterDocument:
    id: int
    title: str
    doc_type: str
    date: Optional[str]
    text: str


@dataclass(frozen=True)
class ClusterExtractionResult:
    collection: EvidenceCollection
    run_id: Optional[str]
    job_id: Optional[str]
    output_dir: Optional[str]
    manifest_path: Optional[str]
    result_payload_path: Optional[str]
    checklist_ndjson_path: Optional[str]


class ClusterChecklistRunner:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._stage_manager = RemoteStageManager(self._settings)

    async def run(
        self,
        backend_run_id: str,
        corpus_id: str,
        documents: List[DocumentReference],
        progress_callback: Optional[ProgressCallback] = None,
        *,
        checklist_spec: Optional[Dict[str, Any]] = None,
        focus_context: Optional[str] = None,
        run_title: Optional[str] = None,
    ) -> ClusterExtractionResult:
        if not documents:
            return ClusterExtractionResult(
                collection=EvidenceCollection(items=[]),
                run_id=None,
                job_id=None,
                output_dir=None,
                manifest_path=None,
                result_payload_path=None,
                checklist_ndjson_path=None,
            )

        request_id = f"cluster_{corpus_id}_{uuid.uuid4().hex[:12]}"
        request_payload = self._build_controller_request(
            corpus_id,
            request_id,
            documents,
            checklist_spec=checklist_spec,
            focus_context=focus_context,
            run_title=run_title,
        )
        stage_paths = await asyncio.to_thread(self._stage_manager.prepare_stage, backend_run_id)
        remote_command = self._stage_manager.build_remote_command(
            stage_paths,
            controller_script=self._settings.cluster_remote_controller_script,
            mode="slurm_extract_strategy",
        )

        producer.info(
            "Starting cluster controller run",
            {
                "backend_run_id": backend_run_id,
                "corpus_id": corpus_id,
                "request_id": request_id,
                "ssh_host": self._settings.cluster_ssh_host,
                "stage_dir": str(stage_paths.run_dir),
                "poll_seconds": self._settings.cluster_poll_seconds,
                "max_wait_seconds": self._settings.cluster_max_wait_seconds,
            },
        )

        process = await asyncio.create_subprocess_exec(
            "ssh",
            self._settings.cluster_ssh_host,
            remote_command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        if process.stdin is None or process.stdout is None or process.stderr is None:
            raise RuntimeError("Failed to open SSH pipes for controller process.")

        serialized_request = json.dumps(request_payload, ensure_ascii=True) + "\n"
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
                            "Cluster progress callback failed",
                            {"corpus_id": corpus_id, "request_id": request_id, "error": str(exc)},
                        )

                if event_type in {"completed", "failed"}:
                    terminal_event_type = event_type
                    terminal_data = event_data

            return_code = await process.wait()
            await stderr_task

            if terminal_event_type is None:
                raise RuntimeError(
                    f"Cluster controller exited without terminal event (exit_code={return_code}, request_id={request_id})."
                )

            if terminal_event_type == "failed":
                detail = self._failure_detail(terminal_data)
                raise RuntimeError(f"Cluster controller reported failure: {detail}")

            if return_code != 0:
                raise RuntimeError(
                    f"Cluster controller exited non-zero after completed event (exit_code={return_code}, request_id={request_id})."
                )

            collection = await self._collection_from_completed_event(terminal_data, documents)
            run_id = self._coerce_string(terminal_data.get("run_id"))
            job_id = self._coerce_string(terminal_data.get("job_id"))
            output_dir = self._coerce_string(terminal_data.get("output_dir"))
            manifest_path = self._coerce_string(terminal_data.get("manifest_path"))
            artifacts = terminal_data.get("artifacts")
            result_payload_path: Optional[str] = None
            checklist_ndjson_path: Optional[str] = None
            if isinstance(artifacts, dict):
                result_payload_path = self._coerce_string(artifacts.get("result_payload_path"))
                checklist_ndjson_path = self._coerce_string(artifacts.get("checklist_ndjson_path"))
            producer.info(
                "Cluster controller run completed",
                {
                    "corpus_id": corpus_id,
                    "request_id": request_id,
                    "extracted_items": len(collection.items),
                    "job_id": terminal_data.get("job_id"),
                },
            )
            return ClusterExtractionResult(
                collection=collection,
                run_id=run_id,
                job_id=job_id,
                output_dir=output_dir,
                manifest_path=manifest_path,
                result_payload_path=result_payload_path,
                checklist_ndjson_path=checklist_ndjson_path,
            )
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
                "Cluster controller stderr",
                {
                    "corpus_id": corpus_id,
                    "request_id": request_id,
                    "message": message,
                },
            )

    def _parse_controller_stdout_line(self, raw_line: bytes) -> Optional[Dict[str, Any]]:
        text_line = raw_line.decode("utf-8", errors="replace").strip()
        if not text_line:
            return None

        try:
            payload = json.loads(text_line)
        except json.JSONDecodeError:
            producer.warning("Received non-JSON line from cluster controller", {"line": text_line[:500]})
            return None

        if not isinstance(payload, dict):
            producer.warning("Received unexpected controller payload type", {"type": type(payload).__name__})
            return None

        event_type = payload.get("event_type")
        if not isinstance(event_type, str):
            producer.warning("Controller payload missing event_type", {"payload": text_line[:500]})
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
        data = payload["data"]
        event_payload = {
            "corpus_id": corpus_id,
            "request_id": request_id,
            "controller_request_id": payload.get("request_id"),
            "seq": payload.get("seq"),
            "event_type": event_type,
            "data": self._summarize_controller_event(event_type, data),
        }
        if event_type == "failed":
            producer.error("Cluster controller event", event_payload)
            return
        producer.info("Cluster controller event", event_payload)

    def _summarize_controller_event(self, event_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        if event_type == "step_completed":
            return {
                "step": data.get("step"),
                "tool_name": data.get("tool_name"),
                "success": data.get("success"),
            }
        if event_type == "slurm_submitted":
            return {
                "job_id": data.get("job_id"),
                "output_dir": data.get("output_dir"),
            }
        if event_type == "slurm_state":
            return {
                "job_id": data.get("job_id"),
                "state": data.get("state"),
            }
        if event_type == "completed":
            completion_stats = data.get("completion_stats")
            summary_stats = completion_stats if isinstance(completion_stats, dict) else None
            return {
                "run_id": data.get("run_id"),
                "job_id": data.get("job_id"),
                "state": data.get("state"),
                "output_dir": data.get("output_dir"),
                "manifest_path": data.get("manifest_path"),
                "completion_stats": summary_stats,
            }
        if event_type == "failed":
            return {
                "job_id": data.get("job_id"),
                "state": data.get("state"),
                "error": data.get("error") or data.get("message"),
            }
        keys_of_interest = (
            "corpus_id",
            "document_count",
            "dataset_name",
            "model",
            "checklist_strategy",
            "checklist_items_count",
            "max_steps",
        )
        return {key: data.get(key) for key in keys_of_interest if key in data}

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
        return "unknown controller error"

    def _build_controller_request(
        self,
        corpus_id: str,
        request_id: str,
        documents: List[DocumentReference],
        *,
        checklist_spec: Optional[Dict[str, Any]] = None,
        focus_context: Optional[str] = None,
        run_title: Optional[str] = None,
    ) -> Dict[str, Any]:
        resolved_docs = self._resolve_documents(documents)
        checklist_strategy = self._settings.cluster_checklist_strategy
        resolved_checklist_spec = checklist_spec or load_cluster_checklist_spec(
            self._settings.cluster_checklist_spec_path,
            strategy=checklist_strategy,
        )
        resolved_focus_context = focus_context or load_cluster_focus_context(run_title)
        request: Dict[str, Any] = {
            "request_id": request_id,
            "input": {
                "corpus_id": str(corpus_id),
                "documents": [
                    {
                        "document_id": str(doc.id),
                        "title": doc.title,
                        "doc_type": doc.doc_type,
                        "date": doc.date,
                        "text": doc.text,
                    }
                    for doc in resolved_docs
                ],
            },
            "model": self._settings.cluster_model_name,
            "checklist_strategy": checklist_strategy,
            "checklist_spec": resolved_checklist_spec,
            "focus_context": resolved_focus_context,
            "resume": bool(self._settings.cluster_resume),
            "debug": bool(self._settings.cluster_debug),
        }

        if checklist_strategy == "all":
            request["max_steps"] = int(self._settings.cluster_max_steps)

        slurm: Dict[str, Any] = {}
        partition = self._settings.cluster_slurm_partition.strip()
        qos = self._settings.cluster_slurm_qos.strip()
        if partition:
            slurm["partition"] = partition
        if qos:
            slurm["qos"] = qos
        if slurm:
            request["slurm"] = slurm

        return request

    def _resolve_documents(self, documents: List[DocumentReference]) -> List[ResolvedClusterDocument]:
        resolved: List[ResolvedClusterDocument] = []
        for doc_ref in documents:
            if not doc_ref.include_full_text or doc_ref.content is None:
                raise ValueError(
                    f"Document '{doc_ref.id}' must include inline full text for cluster extraction."
                )
            text = doc_ref.content
            title = doc_ref.title or doc_ref.alias or f"Document {doc_ref.id}"
            doc_type = doc_ref.type or ""
            date = doc_ref.date

            resolved.append(
                ResolvedClusterDocument(
                    id=int(doc_ref.id),
                    title=title,
                    doc_type=doc_type,
                    date=date,
                    text=text or "",
                )
            )
        return resolved

    async def _collection_from_completed_event(
        self,
        completed_data: Dict[str, Any],
        documents: Sequence[DocumentReference],
    ) -> EvidenceCollection:
        checklist_payload = completed_data.get("checklist")
        document_map_payload = completed_data.get("document_map")

        if not isinstance(checklist_payload, dict):
            checklist_payload, document_map_payload = await asyncio.to_thread(
                self._load_artifact_payload_from_completed_event,
                completed_data,
            )

        return self._collection_from_checklist_payload(
            checklist_payload=checklist_payload,
            document_map_payload=document_map_payload,
            documents=documents,
        )

    def _collection_from_checklist_payload(
        self,
        checklist_payload: Dict[str, Any],
        document_map_payload: Any,
        documents: Sequence[DocumentReference],
    ) -> EvidenceCollection:
        source_document_map = self._build_source_document_map(document_map_payload)
        fallback_document_ids = [int(ref.id) for ref in documents]

        items: List[EvidenceItem] = []
        for bin_id, group_payload in checklist_payload.items():
            if not isinstance(bin_id, str) or not isinstance(group_payload, dict):
                continue
            extracted_values = group_payload.get("extracted")
            if not isinstance(extracted_values, list):
                continue

            for extracted in extracted_values:
                if not isinstance(extracted, dict):
                    continue
                value = extracted.get("value")
                if value is None:
                    continue
                value_text = value if isinstance(value, str) else str(value)
                evidence = self._evidence_pointer_from_extracted(
                    extracted,
                    source_document_map,
                    fallback_document_ids,
                )
                items.append(
                    EvidenceItem(
                        bin_id=bin_id,
                        value=value_text,
                        evidence=evidence,
                    )
                )

        return EvidenceCollection(items=items)

    def _load_artifact_payload_from_completed_event(
        self,
        completed_data: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        run_id = self._require_non_empty_string(completed_data.get("run_id"), "run_id")
        run_dir = self._validate_remote_run_dir(
            self._require_non_empty_string(completed_data.get("run_dir"), "run_dir"),
            run_id,
        )
        manifest_remote_path = self._validate_remote_artifact_path(
            self._require_non_empty_string(completed_data.get("manifest_path"), "manifest_path"),
            run_dir,
            "manifest_path",
        )

        with tempfile.TemporaryDirectory(prefix="cluster_controller_artifacts_") as temp_dir:
            temp_path = Path(temp_dir)
            local_manifest_path = self._rsync_file(manifest_remote_path, temp_path)
            manifest_payload = json.loads(local_manifest_path.read_text(encoding="utf-8"))
            if not isinstance(manifest_payload, dict):
                raise RuntimeError("Controller manifest payload must be a JSON object.")
            manifest_run_id = manifest_payload.get("run_id")
            if manifest_run_id != run_id:
                raise RuntimeError(
                    f"Controller manifest run_id mismatch: expected '{run_id}', got '{manifest_run_id}'."
                )

            artifacts = manifest_payload.get("artifacts")
            if not isinstance(artifacts, dict):
                raise RuntimeError("Controller manifest is missing an artifacts object.")

            checklist_remote_path = self._validate_remote_artifact_path(
                self._require_non_empty_string(
                    artifacts.get("checklist_ndjson_path"),
                    "artifacts.checklist_ndjson_path",
                ),
                run_dir,
                "artifacts.checklist_ndjson_path",
            )
            document_map_remote_path = self._validate_remote_artifact_path(
                self._require_non_empty_string(
                    artifacts.get("document_map_path"),
                    "artifacts.document_map_path",
                ),
                run_dir,
                "artifacts.document_map_path",
            )

            local_checklist_path = self._rsync_file(checklist_remote_path, temp_path)
            local_document_map_path = self._rsync_file(document_map_remote_path, temp_path)

            checklist_payload = self._parse_checklist_ndjson(local_checklist_path)
            document_map_payload = json.loads(local_document_map_path.read_text(encoding="utf-8"))
            if not isinstance(document_map_payload, dict):
                raise RuntimeError("Controller document_map payload must be a JSON object.")

            return checklist_payload, document_map_payload

    def _validate_remote_run_dir(self, run_dir: str, run_id: str) -> PurePosixPath:
        run_dir_path = PurePosixPath(run_dir)
        if not run_dir_path.is_absolute():
            raise RuntimeError(f"Controller run_dir must be absolute: '{run_dir}'.")
        if len(run_dir_path.parts) < 3 or tuple(run_dir_path.parts[-3:]) != ("controller", "runs", run_id):
            raise RuntimeError(
                f"Controller run_dir '{run_dir}' is not under the expected controller/runs/<run_id> layout."
            )
        return run_dir_path

    def _validate_remote_artifact_path(
        self,
        remote_path: str,
        run_dir: PurePosixPath,
        field_name: str,
    ) -> PurePosixPath:
        artifact_path = PurePosixPath(remote_path)
        if not artifact_path.is_absolute():
            raise RuntimeError(f"Controller {field_name} must be an absolute path: '{remote_path}'.")
        try:
            artifact_path.relative_to(run_dir)
        except ValueError as exc:
            raise RuntimeError(
                f"Controller {field_name} must be located under run_dir '{run_dir}'. Got '{remote_path}'."
            ) from exc
        return artifact_path

    def _require_non_empty_string(self, value: Any, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(f"Controller payload missing required non-empty string field '{field_name}'.")
        return value.strip()

    def _rsync_file(self, remote_path: PurePosixPath, destination_dir: Path) -> Path:
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
            raise RuntimeError(f"Failed to rsync remote artifact '{remote_path}': {detail}")

        local_path = destination_dir / remote_path.name
        if not local_path.exists():
            raise RuntimeError(
                f"Remote artifact pull reported success but local file was not found: '{local_path}'."
            )
        return local_path

    def _parse_checklist_ndjson(self, checklist_path: Path) -> Dict[str, Any]:
        checklist_payload: Dict[str, Any] = {}
        with checklist_path.open("r", encoding="utf-8") as checklist_file:
            for line_number, line in enumerate(checklist_file, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    record = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(
                        f"Failed to parse checklist_ndjson line {line_number} in '{checklist_path}'."
                    ) from exc

                if not isinstance(record, dict):
                    continue
                key = record.get("key")
                if not isinstance(key, str) or not key.strip():
                    continue

                extracted = record.get("extracted")
                if isinstance(extracted, list):
                    checklist_payload[key] = {"extracted": extracted}

        if not checklist_payload:
            raise RuntimeError(f"Checklist NDJSON did not contain any checklist records: '{checklist_path}'.")
        return checklist_payload

    def _build_source_document_map(self, document_map_payload: Any) -> Dict[str, int]:
        result: Dict[str, int] = {}
        if not isinstance(document_map_payload, dict):
            return result

        by_source = document_map_payload.get("by_source_document_id")
        if isinstance(by_source, dict):
            for raw_key, raw_doc_id in by_source.items():
                parsed_doc_id = self._coerce_int(raw_doc_id)
                if parsed_doc_id is None:
                    continue
                self._set_document_aliases(result, raw_key, parsed_doc_id)

        documents = document_map_payload.get("documents")
        if isinstance(documents, list):
            for record in documents:
                if not isinstance(record, dict):
                    continue
                raw_doc_id = record.get("doc_id")
                parsed_doc_id = self._coerce_int(raw_doc_id)
                if parsed_doc_id is None:
                    continue
                self._set_document_aliases(result, raw_doc_id, parsed_doc_id)
                self._set_document_aliases(result, record.get("source_document_id"), parsed_doc_id)

        return result

    def _set_document_aliases(self, mapping: Dict[str, int], key: Any, doc_id: int) -> None:
        if key is None:
            return
        key_text = str(key)
        stripped = key_text.strip()
        if not stripped:
            return
        mapping[stripped] = doc_id
        lowered = stripped.casefold()
        mapping[lowered] = doc_id

    def _evidence_pointer_from_extracted(
        self,
        extracted: Dict[str, Any],
        source_document_map: Dict[str, int],
        fallback_document_ids: Sequence[int],
    ) -> EvidencePointer:
        raw_evidence = extracted.get("evidence")
        evidence_entries: List[Dict[str, Any]] = []
        if isinstance(raw_evidence, dict):
            evidence_entries = [raw_evidence]
        elif isinstance(raw_evidence, list):
            evidence_entries = [item for item in raw_evidence if isinstance(item, dict)]

        selected_entry: Dict[str, Any] = {}
        selected_document_id: Optional[int] = None

        for entry in evidence_entries:
            parsed = self._resolve_document_id(entry, source_document_map)
            if parsed is not None:
                selected_entry = entry
                selected_document_id = parsed
                break

        if selected_document_id is None:
            if evidence_entries:
                selected_entry = evidence_entries[0]
                selected_document_id = self._resolve_document_id(selected_entry, source_document_map)
            if selected_document_id is None:
                selected_document_id = self._default_document_id(fallback_document_ids)

        verified_raw = selected_entry.get("verified")
        verified = True if verified_raw is None else bool(verified_raw)
        start_offset_raw = selected_entry.get("start_offset")
        if start_offset_raw is None:
            start_offset_raw = selected_entry.get("startOffset")
        end_offset_raw = selected_entry.get("end_offset")
        if end_offset_raw is None:
            end_offset_raw = selected_entry.get("endOffset")

        return EvidencePointer(
            document_id=selected_document_id,
            location=self._coerce_string(selected_entry.get("location")),
            start_offset=self._coerce_int(start_offset_raw),
            end_offset=self._coerce_int(end_offset_raw),
            text=self._coerce_string(selected_entry.get("text")),
            verified=verified,
        )

    def _resolve_document_id(self, evidence: Dict[str, Any], source_document_map: Dict[str, int]) -> Optional[int]:
        for key in ("source_document_id", "sourceDocumentId", "document_id", "documentId", "doc_id", "docId"):
            parsed = self._coerce_int(evidence.get(key))
            if parsed is not None:
                return parsed

        source_document_id = evidence.get("source_document_id")
        if source_document_id is None:
            source_document_id = evidence.get("sourceDocumentId")
        if source_document_id is None:
            return None

        if isinstance(source_document_id, int):
            return source_document_id

        source_text = str(source_document_id).strip()
        if not source_text:
            return None

        mapped = source_document_map.get(source_text)
        if mapped is not None:
            return mapped

        mapped = source_document_map.get(source_text.casefold())
        if mapped is not None:
            return mapped

        return self._coerce_int(source_text)

    def _default_document_id(self, fallback_document_ids: Sequence[int]) -> int:
        if len(fallback_document_ids) == 1:
            return int(fallback_document_ids[0])
        return SUMMARY_DOCUMENT_ID

    def _coerce_int(self, value: Any) -> Optional[int]:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            try:
                return int(text)
            except ValueError:
                return None
        return None

    def _coerce_string(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return str(value)


_RUNNER = ClusterChecklistRunner()


def validate_cluster_runtime_prerequisites() -> None:
    settings = get_settings()
    if settings.cluster_run_mode == "spoof":
        validate_spoof_fixture_dir(
            settings.cluster_spoof_extraction_fixture_dir,
            label="Spoof extraction",
            required_files=(
                "events.ndjson",
                "request.json",
                "manifest.json",
                "result_payload.json",
                "checklist.json",
                "document_map.json",
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
        "MULTI_DOCUMENT_CLUSTER_REMOTE_CONTROLLER_SCRIPT": settings.cluster_remote_controller_script,
    }
    for env_name, value in required_text_fields.items():
        if not isinstance(value, str) or not value.strip():
            config_errors.append(f"{env_name} must be set.")

    missing_binaries = [name for name in ("ssh", "rsync") if shutil.which(name) is None]
    for binary in missing_binaries:
        config_errors.append(f"Required local binary '{binary}' was not found on PATH.")

    if not settings.cluster_remote_controller_script.startswith("interface_agents/"):
        config_errors.append(
            "MULTI_DOCUMENT_CLUSTER_REMOTE_CONTROLLER_SCRIPT must be a path under interface_agents/."
        )

    try:
        RemoteStageManager(settings).validate_local_prerequisites()
    except RuntimeError as exc:
        config_errors.append(str(exc))

    if config_errors:
        joined = " ".join(config_errors)
        raise RuntimeError(f"Cluster extraction prerequisites are not satisfied. {joined}")


async def run_cluster_extraction(
    backend_run_id: str,
    corpus_id: str,
    documents: List[DocumentReference],
    progress_callback: Optional[ProgressCallback] = None,
    *,
    checklist_spec: Optional[Dict[str, Any]] = None,
    focus_context: Optional[str] = None,
    run_title: Optional[str] = None,
) -> ClusterExtractionResult:
    return await _RUNNER.run(
        backend_run_id,
        corpus_id,
        documents,
        progress_callback=progress_callback,
        checklist_spec=checklist_spec,
        focus_context=focus_context,
        run_title=run_title,
    )
