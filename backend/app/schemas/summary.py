from __future__ import annotations

from enum import Enum
from typing import List, Literal, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class SummaryJobStatus(str, Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class SummarySlurmOptions(BaseModel):
    partition: Optional[str] = None
    qos: Optional[str] = None
    model_config = ConfigDict(extra="forbid", populate_by_name=True, protected_namespaces=())


class SummaryRequest(BaseModel):
    model: Optional[str] = Field(
        None,
        description="Override model name for cluster summary generation.",
        serialization_alias="model",
        validation_alias=AliasChoices("model", "modelName", "model_name"),
    )
    max_steps: Optional[int] = Field(
        None,
        ge=1,
        description="Maximum reasoning steps for summary-agent runtime.",
        serialization_alias="maxSteps",
        validation_alias=AliasChoices("maxSteps", "max_steps"),
    )
    reasoning_effort: Optional[Literal["low", "medium", "high"]] = Field(
        None,
        description="Reasoning effort level for summary-agent runtime.",
        serialization_alias="reasoningEffort",
        validation_alias=AliasChoices("reasoningEffort", "reasoning_effort"),
    )
    summary_constraints: Optional[List[str]] = Field(
        None,
        description="Optional summary style/content constraints passed to runtime prompt assembly.",
        serialization_alias="summaryConstraints",
        validation_alias=AliasChoices("summaryConstraints", "summary_constraints"),
    )
    focus_context: Optional[str] = Field(
        None,
        description=(
            "Optional summary focus context template/text. Supports runtime placeholder "
            "#CASE_TITLE."
        ),
        serialization_alias="focusContext",
        validation_alias=AliasChoices("focusContext", "focus_context"),
    )
    k_recent_tool_outputs: Optional[int] = Field(
        None,
        ge=1,
        description="How many recent tool outputs should be included verbatim in snapshots.",
        serialization_alias="kRecentToolOutputs",
        validation_alias=AliasChoices("kRecentToolOutputs", "k_recent_tool_outputs"),
    )
    resume: Optional[bool] = Field(
        None,
        description="Resume mode forwarded to summary-agent runtime.",
    )
    debug: Optional[bool] = Field(
        None,
        description="Debug mode forwarded to summary-agent runtime.",
    )
    prompt_config: Optional[str] = Field(
        None,
        description="Optional remote prompt config path.",
        serialization_alias="promptConfig",
        validation_alias=AliasChoices("promptConfig", "prompt_config"),
    )
    slurm: Optional[SummarySlurmOptions] = None
    python_bin: Optional[str] = Field(
        None,
        description="Optional python binary override forwarded to the remote controller.",
        serialization_alias="pythonBin",
        validation_alias=AliasChoices("pythonBin", "python_bin"),
    )
    model_config = ConfigDict(extra="forbid", populate_by_name=True, protected_namespaces=())


class SummaryJob(BaseModel):
    id: str
    case_id: str
    status: SummaryJobStatus
    summary_text: Optional[str] = None
    error: Optional[str] = None
    run_id: Optional[str] = None
    remote_job_id: Optional[str] = Field(
        None,
        serialization_alias="remoteJobId",
        validation_alias=AliasChoices("remoteJobId", "remote_job_id"),
    )
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class SummaryJobEnvelope(BaseModel):
    job: SummaryJob
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class SummaryPromptResponse(BaseModel):
    prompt: str
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
