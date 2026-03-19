from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class RunRecord(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_type: Mapped[str] = mapped_column(String, nullable=False)
    source_case_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    case_title: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)

    extraction_config_json: Mapped[str] = mapped_column(Text, nullable=False)
    summary_config_json: Mapped[str] = mapped_column(Text, nullable=False)

    extraction_status: Mapped[str] = mapped_column(String, nullable=False, default="not_started")
    extraction_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_progress_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_remote_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    extraction_remote_job_id: Mapped[str | None] = mapped_column(String, nullable=True)
    extraction_remote_output_dir: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_manifest_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_result_payload_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_checklist_ndjson_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    summary_status: Mapped[str] = mapped_column(String, nullable=False, default="not_started")
    summary_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_progress_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_remote_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    summary_remote_job_id: Mapped[str | None] = mapped_column(String, nullable=True)
    summary_remote_output_dir: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_manifest_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_result_payload_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_summary_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    documents: Mapped[list["RunDocument"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )


class RunDocument(Base):
    __tablename__ = "run_documents"

    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), primary_key=True)
    document_id: Mapped[int] = mapped_column(Integer, primary_key=True)

    title: Mapped[str | None] = mapped_column(String, nullable=True)
    type: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String, nullable=True)
    court: Mapped[str | None] = mapped_column(String, nullable=True)
    state: Mapped[str | None] = mapped_column(String, nullable=True)
    ecf_number: Mapped[str | None] = mapped_column(String, nullable=True)
    file_url: Mapped[str | None] = mapped_column(String, nullable=True)
    external_url: Mapped[str | None] = mapped_column(String, nullable=True)
    clearinghouse_link: Mapped[str | None] = mapped_column(String, nullable=True)
    text_url: Mapped[str | None] = mapped_column(String, nullable=True)
    date: Mapped[str | None] = mapped_column(String, nullable=True)
    date_is_estimate: Mapped[bool | None] = mapped_column(nullable=True)
    date_not_available: Mapped[bool | None] = mapped_column(nullable=True)
    is_docket: Mapped[bool] = mapped_column(nullable=False, default=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    run: Mapped[RunRecord] = relationship(back_populates="documents")
