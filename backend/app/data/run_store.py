from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Dict, List, Optional, Protocol

from app.db.models import RunDocument, RunRecord
from app.db.session import get_session
from app.schemas.documents import Document


@dataclass(frozen=True)
class StoredRun:
    id: str
    source_type: str
    source_case_id: Optional[str]
    case_title: str
    created_at: str
    extraction_config: Dict[str, Any]
    summary_config: Dict[str, Any]
    extraction_status: str
    extraction_error: Optional[str]
    extraction_progress: Optional[Dict[str, Any]]
    extraction_result: Optional[Dict[str, Any]]
    extraction_remote_run_id: Optional[str]
    extraction_remote_job_id: Optional[str]
    extraction_remote_output_dir: Optional[str]
    extraction_manifest_path: Optional[str]
    extraction_result_payload_path: Optional[str]
    extraction_checklist_ndjson_path: Optional[str]
    summary_status: str
    summary_error: Optional[str]
    summary_progress: Optional[Dict[str, Any]]
    summary_result: Optional[Dict[str, Any]]
    summary_text: Optional[str]
    summary_remote_run_id: Optional[str]
    summary_remote_job_id: Optional[str]
    summary_remote_output_dir: Optional[str]
    summary_manifest_path: Optional[str]
    summary_result_payload_path: Optional[str]
    summary_summary_path: Optional[str]
    documents: List[Document]


class RunStore(Protocol):
    def create_run(
        self,
        *,
        run_id: str,
        source_type: str,
        source_case_id: Optional[str],
        case_title: str,
        created_at: str,
        documents: List[Document],
        extraction_config: Dict[str, Any],
        summary_config: Dict[str, Any],
    ) -> None:
        ...

    def get_run(self, run_id: str) -> Optional[StoredRun]:
        ...


class SqlRunStore:
    def __init__(self) -> None:
        self._session_factory = get_session

    def create_run(
        self,
        *,
        run_id: str,
        source_type: str,
        source_case_id: Optional[str],
        case_title: str,
        created_at: str,
        documents: List[Document],
        extraction_config: Dict[str, Any],
        summary_config: Dict[str, Any],
    ) -> None:
        session = self._session_factory()
        try:
            session.query(RunDocument).filter(RunDocument.run_id == run_id).delete()
            session.query(RunRecord).filter(RunRecord.id == run_id).delete()

            record = RunRecord(
                id=run_id,
                source_type=source_type,
                source_case_id=source_case_id,
                case_title=case_title,
                created_at=created_at,
                extraction_config_json=self._dump_json(extraction_config),
                summary_config_json=self._dump_json(summary_config),
                extraction_status="not_started",
                summary_status="not_started",
            )
            session.add(record)

            for doc in documents:
                session.add(
                    RunDocument(
                        run_id=run_id,
                        document_id=int(doc.id),
                        title=doc.title,
                        type=doc.type,
                        description=doc.description,
                        source=doc.source,
                        court=doc.court,
                        state=doc.state,
                        ecf_number=doc.ecf_number,
                        file_url=doc.file_url,
                        external_url=doc.external_url,
                        clearinghouse_link=doc.clearinghouse_link,
                        text_url=doc.text_url,
                        date=doc.date,
                        date_is_estimate=doc.date_is_estimate,
                        date_not_available=doc.date_not_available,
                        is_docket=bool(doc.is_docket),
                        content=doc.content,
                    )
                )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_run(self, run_id: str) -> Optional[StoredRun]:
        session = self._session_factory()
        try:
            record = session.get(RunRecord, run_id)
            if record is None:
                return None

            docs = (
                session.query(RunDocument)
                .filter(RunDocument.run_id == run_id)
                .order_by(RunDocument.document_id.asc())
                .all()
            )
            documents = [
                Document(
                    id=int(doc.document_id),
                    title=doc.title or f"Document {doc.document_id}",
                    type=doc.type,
                    description=doc.description,
                    source=doc.source,
                    court=doc.court,
                    state=doc.state,
                    ecf_number=doc.ecf_number,
                    file_url=doc.file_url,
                    external_url=doc.external_url,
                    clearinghouse_link=doc.clearinghouse_link,
                    text_url=doc.text_url,
                    date=doc.date,
                    date_is_estimate=doc.date_is_estimate,
                    date_not_available=doc.date_not_available,
                    is_docket=bool(doc.is_docket),
                    content=doc.content,
                )
                for doc in docs
            ]

            return StoredRun(
                id=record.id,
                source_type=record.source_type,
                source_case_id=record.source_case_id,
                case_title=record.case_title,
                created_at=record.created_at,
                extraction_config=self._load_json(record.extraction_config_json),
                summary_config=self._load_json(record.summary_config_json),
                extraction_status=record.extraction_status,
                extraction_error=record.extraction_error,
                extraction_progress=self._load_json(record.extraction_progress_json),
                extraction_result=self._load_json(record.extraction_result_json),
                extraction_remote_run_id=record.extraction_remote_run_id,
                extraction_remote_job_id=record.extraction_remote_job_id,
                extraction_remote_output_dir=record.extraction_remote_output_dir,
                extraction_manifest_path=record.extraction_manifest_path,
                extraction_result_payload_path=record.extraction_result_payload_path,
                extraction_checklist_ndjson_path=record.extraction_checklist_ndjson_path,
                summary_status=record.summary_status,
                summary_error=record.summary_error,
                summary_progress=self._load_json(record.summary_progress_json),
                summary_result=self._load_json(record.summary_result_json),
                summary_text=record.summary_text,
                summary_remote_run_id=record.summary_remote_run_id,
                summary_remote_job_id=record.summary_remote_job_id,
                summary_remote_output_dir=record.summary_remote_output_dir,
                summary_manifest_path=record.summary_manifest_path,
                summary_result_payload_path=record.summary_result_payload_path,
                summary_summary_path=record.summary_summary_path,
                documents=documents,
            )
        finally:
            session.close()

    def update_extraction_config(self, run_id: str, extraction_config: Dict[str, Any]) -> None:
        session = self._session_factory()
        try:
            record = self._require_record(session, run_id)
            record.extraction_config_json = self._dump_json(extraction_config)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def update_summary_config(self, run_id: str, summary_config: Dict[str, Any]) -> None:
        session = self._session_factory()
        try:
            record = self._require_record(session, run_id)
            record.summary_config_json = self._dump_json(summary_config)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def update_extraction_state(
        self,
        run_id: str,
        *,
        status: Optional[str] = None,
        error: Optional[str] = None,
        progress: Optional[Dict[str, Any]] = None,
        remote_run_id: Optional[str] = None,
        remote_job_id: Optional[str] = None,
        remote_output_dir: Optional[str] = None,
    ) -> None:
        session = self._session_factory()
        try:
            record = self._require_record(session, run_id)
            if status is not None:
                record.extraction_status = status
            record.extraction_error = error
            if progress is not None:
                record.extraction_progress_json = self._dump_json(progress)
            if remote_run_id is not None:
                record.extraction_remote_run_id = remote_run_id
            if remote_job_id is not None:
                record.extraction_remote_job_id = remote_job_id
            if remote_output_dir is not None:
                record.extraction_remote_output_dir = remote_output_dir
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def store_extraction_result(
        self,
        run_id: str,
        *,
        extraction_result: Dict[str, Any],
        remote_run_id: Optional[str],
        remote_job_id: Optional[str],
        remote_output_dir: Optional[str],
        manifest_path: Optional[str],
        result_payload_path: Optional[str],
        checklist_ndjson_path: Optional[str],
    ) -> None:
        session = self._session_factory()
        try:
            record = self._require_record(session, run_id)
            record.extraction_status = "succeeded"
            record.extraction_error = None
            record.extraction_result_json = self._dump_json(extraction_result)
            record.extraction_remote_run_id = remote_run_id
            record.extraction_remote_job_id = remote_job_id
            record.extraction_remote_output_dir = remote_output_dir
            record.extraction_manifest_path = manifest_path
            record.extraction_result_payload_path = result_payload_path
            record.extraction_checklist_ndjson_path = checklist_ndjson_path
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def update_extraction_result(self, run_id: str, extraction_result: Dict[str, Any]) -> None:
        session = self._session_factory()
        try:
            record = self._require_record(session, run_id)
            record.extraction_result_json = self._dump_json(extraction_result)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def update_summary_state(
        self,
        run_id: str,
        *,
        status: Optional[str] = None,
        error: Optional[str] = None,
        progress: Optional[Dict[str, Any]] = None,
        remote_run_id: Optional[str] = None,
        remote_job_id: Optional[str] = None,
        remote_output_dir: Optional[str] = None,
    ) -> None:
        session = self._session_factory()
        try:
            record = self._require_record(session, run_id)
            if status is not None:
                record.summary_status = status
            record.summary_error = error
            if progress is not None:
                record.summary_progress_json = self._dump_json(progress)
            if remote_run_id is not None:
                record.summary_remote_run_id = remote_run_id
            if remote_job_id is not None:
                record.summary_remote_job_id = remote_job_id
            if remote_output_dir is not None:
                record.summary_remote_output_dir = remote_output_dir
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def store_summary_result(
        self,
        run_id: str,
        *,
        summary_text: str,
        summary_result: Dict[str, Any],
        remote_run_id: Optional[str],
        remote_job_id: Optional[str],
        remote_output_dir: Optional[str],
        manifest_path: Optional[str],
        result_payload_path: Optional[str],
        summary_path: Optional[str],
    ) -> None:
        session = self._session_factory()
        try:
            record = self._require_record(session, run_id)
            record.summary_status = "succeeded"
            record.summary_error = None
            record.summary_text = summary_text
            record.summary_result_json = self._dump_json(summary_result)
            record.summary_remote_run_id = remote_run_id
            record.summary_remote_job_id = remote_job_id
            record.summary_remote_output_dir = remote_output_dir
            record.summary_manifest_path = manifest_path
            record.summary_result_payload_path = result_payload_path
            record.summary_summary_path = summary_path
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def clear_all(self) -> None:
        session = self._session_factory()
        try:
            session.query(RunDocument).delete()
            session.query(RunRecord).delete()
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _require_record(self, session, run_id: str) -> RunRecord:
        record = session.get(RunRecord, run_id)
        if record is None:
            raise KeyError(f"Run '{run_id}' was not found.")
        return record

    def _dump_json(self, value: Dict[str, Any]) -> str:
        return json.dumps(value, ensure_ascii=False)

    def _load_json(self, raw_value: Optional[str]) -> Optional[Dict[str, Any]]:
        if not isinstance(raw_value, str) or not raw_value.strip():
            return None
        value = json.loads(raw_value)
        if not isinstance(value, dict):
            return None
        return value
