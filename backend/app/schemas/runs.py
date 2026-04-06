from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


ReasoningEffort = Literal["low", "medium", "high"]
WorkflowStage = Literal["setup", "extraction_wait", "review", "summary_wait", "workspace"]


class RunDocumentPayload(BaseModel):
    id: int
    title: str
    type: Optional[str] = None
    description: Optional[str] = None
    source: Optional[str] = None
    date: Optional[str] = None
    ecf_number: Optional[str] = Field(
        None,
        serialization_alias="ecfNumber",
        validation_alias=AliasChoices("ecf_number", "ecfNumber"),
    )
    is_docket: bool = Field(
        False,
        serialization_alias="isDocket",
        validation_alias=AliasChoices("is_docket", "isDocket"),
    )
    content: str

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RunDocumentMetadata(BaseModel):
    id: int
    title: str
    type: Optional[str] = None
    source: Optional[str] = None
    date: Optional[str] = None
    ecf_number: Optional[str] = Field(
        None,
        serialization_alias="ecfNumber",
        validation_alias=AliasChoices("ecf_number", "ecfNumber"),
    )
    is_docket: bool = Field(
        False,
        serialization_alias="isDocket",
        validation_alias=AliasChoices("is_docket", "isDocket"),
    )

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ExtractionChecklistSpecItem(BaseModel):
    key: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    user_instruction: str = Field(
        ...,
        min_length=1,
        serialization_alias="userInstruction",
        validation_alias=AliasChoices("userInstruction", "user_instruction"),
    )
    constraints: List[str] = Field(default_factory=list)
    max_steps: int = Field(
        ...,
        ge=1,
        serialization_alias="maxSteps",
        validation_alias=AliasChoices("maxSteps", "max_steps"),
    )
    reasoning_effort: ReasoningEffort = Field(
        ...,
        serialization_alias="reasoningEffort",
        validation_alias=AliasChoices("reasoningEffort", "reasoning_effort"),
    )

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ExtractionChecklistSpec(BaseModel):
    checklist_items: List[ExtractionChecklistSpecItem] = Field(
        default_factory=list,
        serialization_alias="checklistItems",
        validation_alias=AliasChoices("checklistItems", "checklist_items"),
    )

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RunExtractionConfig(BaseModel):
    focus_context: str = Field(
        ...,
        min_length=1,
        serialization_alias="focusContext",
        validation_alias=AliasChoices("focusContext", "focus_context"),
    )
    checklist_spec: ExtractionChecklistSpec = Field(
        ...,
        serialization_alias="checklistSpec",
        validation_alias=AliasChoices("checklistSpec", "checklist_spec"),
    )

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RunSummaryConfig(BaseModel):
    focus_context: str = Field(
        ...,
        min_length=1,
        serialization_alias="focusContext",
        validation_alias=AliasChoices("focusContext", "focus_context"),
    )
    reasoning_effort: ReasoningEffort = Field(
        ...,
        serialization_alias="reasoningEffort",
        validation_alias=AliasChoices("reasoningEffort", "reasoning_effort"),
    )
    max_steps: int = Field(
        ...,
        ge=1,
        serialization_alias="maxSteps",
        validation_alias=AliasChoices("maxSteps", "max_steps"),
    )

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RunCreateResponse(BaseModel):
    run_id: str = Field(
        ...,
        serialization_alias="runId",
        validation_alias=AliasChoices("runId", "run_id"),
    )
    source_type: str = Field(
        ...,
        serialization_alias="sourceType",
        validation_alias=AliasChoices("sourceType", "source_type"),
    )
    title: str
    created_at: datetime = Field(
        ...,
        serialization_alias="createdAt",
        validation_alias=AliasChoices("createdAt", "created_at"),
    )
    extraction_status: str = Field(
        ...,
        serialization_alias="extractionStatus",
        validation_alias=AliasChoices("extractionStatus", "extraction_status"),
    )
    summary_status: str = Field(
        ...,
        serialization_alias="summaryStatus",
        validation_alias=AliasChoices("summaryStatus", "summary_status"),
    )
    workflow_stage: WorkflowStage = Field(
        ...,
        serialization_alias="workflowStage",
        validation_alias=AliasChoices("workflowStage", "workflow_stage"),
    )
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
    documents: List[RunDocumentMetadata] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RunDefaultConfigResponse(BaseModel):
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


class RunStageStatus(BaseModel):
    status: str
    phase: Optional[str] = None
    event_type: Optional[str] = Field(
        None,
        serialization_alias="eventType",
        validation_alias=AliasChoices("eventType", "event_type"),
    )
    slurm_state: Optional[str] = Field(
        None,
        serialization_alias="slurmState",
        validation_alias=AliasChoices("slurmState", "slurm_state"),
    )
    item_index: Optional[int] = Field(
        None,
        serialization_alias="itemIndex",
        validation_alias=AliasChoices("itemIndex", "item_index"),
    )
    items_total: Optional[int] = Field(
        None,
        serialization_alias="itemsTotal",
        validation_alias=AliasChoices("itemsTotal", "items_total"),
    )
    config_name: Optional[str] = Field(
        None,
        serialization_alias="configName",
        validation_alias=AliasChoices("configName", "config_name"),
    )
    tool_name: Optional[str] = Field(
        None,
        serialization_alias="toolName",
        validation_alias=AliasChoices("toolName", "tool_name"),
    )
    tool_success: Optional[bool] = Field(
        None,
        serialization_alias="toolSuccess",
        validation_alias=AliasChoices("toolSuccess", "tool_success"),
    )
    current_step: Optional[int] = Field(
        None,
        serialization_alias="currentStep",
        validation_alias=AliasChoices("currentStep", "current_step"),
    )
    max_steps: Optional[int] = Field(
        None,
        serialization_alias="maxSteps",
        validation_alias=AliasChoices("maxSteps", "max_steps"),
    )
    error: Optional[str] = None
    remote_run_id: Optional[str] = Field(
        None,
        serialization_alias="remoteRunId",
        validation_alias=AliasChoices("remoteRunId", "remote_run_id"),
    )
    remote_job_id: Optional[str] = Field(
        None,
        serialization_alias="remoteJobId",
        validation_alias=AliasChoices("remoteJobId", "remote_job_id"),
    )

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RunExtractionStatusEnvelope(BaseModel):
    run_id: str = Field(
        ...,
        serialization_alias="runId",
        validation_alias=AliasChoices("runId", "run_id"),
    )
    extraction: RunStageStatus

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RunSummaryStatusEnvelope(BaseModel):
    run_id: str = Field(
        ...,
        serialization_alias="runId",
        validation_alias=AliasChoices("runId", "run_id"),
    )
    summary: RunStageStatus
    summary_text: Optional[str] = Field(
        None,
        serialization_alias="summaryText",
        validation_alias=AliasChoices("summaryText", "summary_text"),
    )

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RunExtractionStartRequest(BaseModel):
    extraction_config: Optional[RunExtractionConfig] = Field(
        default=None,
        serialization_alias="extractionConfig",
        validation_alias=AliasChoices("extractionConfig", "extraction_config"),
    )

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RunSummaryStartRequest(BaseModel):
    summary_config: Optional[RunSummaryConfig] = Field(
        default=None,
        serialization_alias="summaryConfig",
        validation_alias=AliasChoices("summaryConfig", "summary_config"),
    )

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RunWorkflowStageUpdateRequest(BaseModel):
    workflow_stage: WorkflowStage = Field(
        ...,
        serialization_alias="workflowStage",
        validation_alias=AliasChoices("workflowStage", "workflow_stage"),
    )

    model_config = ConfigDict(extra="forbid", populate_by_name=True)
