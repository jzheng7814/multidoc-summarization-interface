from __future__ import annotations

from typing import List, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

SUMMARY_DOCUMENT_ID = -1


class LlmEvidencePointer(BaseModel):
    """Evidence anchor returned directly by the LLM (sentence-level)."""

    document_id: int = Field(
        ...,
        serialization_alias="documentId",
        validation_alias=AliasChoices("documentId", "document_id", "source_document", "sourceDocument"),
    )
    sentence_ids: List[int] = Field(
        ...,
        min_length=1,
        serialization_alias="sentenceIds",
        validation_alias=AliasChoices("sentenceIds", "sentence_ids"),
    )

    @field_validator("document_id", mode="before")
    @classmethod
    def _require_integer_document_id(cls, value: object) -> int:
        if isinstance(value, int):
            return value
        raise TypeError("document_id must be provided as an integer")

    @field_validator("sentence_ids", mode="before")
    @classmethod
    def _coerce_sentence_ids(cls, value: object) -> List[int]:
        if isinstance(value, (list, tuple)):
            result: List[int] = []
            for entry in value:
                if not isinstance(entry, int):
                    raise TypeError("sentence_ids must be a list of integers")
                result.append(entry)
            return result
        raise TypeError("sentence_ids must be provided as a list of integers")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class EvidencePointer(BaseModel):
    """Offset-based evidence anchor used after resolution/storage."""

    document_id: int = Field(
        ...,
        serialization_alias="documentId",
        validation_alias=AliasChoices("documentId", "document_id", "source_document", "sourceDocument"),
    )
    location: Optional[str] = Field(
        None,
        serialization_alias="location",
        validation_alias=AliasChoices("location",),
    )
    start_offset: Optional[int] = Field(
        None,
        ge=0,
        serialization_alias="startOffset",
        validation_alias=AliasChoices("startOffset", "start_offset"),
    )
    end_offset: Optional[int] = Field(
        None,
        ge=0,
        serialization_alias="endOffset",
        validation_alias=AliasChoices("endOffset", "end_offset"),
    )
    text: Optional[str] = Field(
        None,
        serialization_alias="text",
        validation_alias=AliasChoices("text",),
    )
    verified: bool = Field(
        True,
        serialization_alias="verified",
        validation_alias=AliasChoices("verified",),
    )

    @field_validator("document_id", mode="before")
    @classmethod
    def _require_integer_document_id(cls, value: object) -> int:
        if isinstance(value, int):
            return value
        raise TypeError("document_id must be provided as an integer")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class LlmEvidenceItem(BaseModel):
    """Single extracted item tagged to an evidence bin (LLM response shape)."""

    bin_id: str = Field(
        ...,
        serialization_alias="binId",
        validation_alias=AliasChoices("binId", "bin_id", "category_id", "categoryId"),
    )
    value: str
    evidence: LlmEvidencePointer

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class LlmEvidenceCollection(BaseModel):
    """Flat collection of extracted evidence items as emitted by the LLM."""

    items: List[LlmEvidenceItem] = Field(
        default_factory=list,
        serialization_alias="items",
        validation_alias=AliasChoices("items", "entries"),
    )

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class EvidenceItem(BaseModel):
    """Offset-based evidence item after resolution."""

    bin_id: str = Field(
        ...,
        serialization_alias="binId",
        validation_alias=AliasChoices("binId", "bin_id", "category_id", "categoryId"),
    )
    value: str
    evidence: EvidencePointer

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class EvidenceCollection(BaseModel):
    """Flat collection of resolved evidence items."""

    items: List[EvidenceItem] = Field(
        default_factory=list,
        serialization_alias="items",
        validation_alias=AliasChoices("items", "entries"),
    )

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class EvidenceCategoryValue(BaseModel):
    id: str
    value: str
    text: Optional[str] = None
    document_id: Optional[int] = Field(
        None,
        serialization_alias="documentId",
        validation_alias=AliasChoices("documentId", "document_id"),
    )
    start_offset: Optional[int] = Field(
        None,
        ge=0,
        serialization_alias="startOffset",
        validation_alias=AliasChoices("startOffset", "start_offset"),
    )
    end_offset: Optional[int] = Field(
        None,
        ge=0,
        serialization_alias="endOffset",
        validation_alias=AliasChoices("endOffset", "end_offset"),
    )

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class EvidenceCategory(BaseModel):
    id: str
    label: str
    color: str
    values: List[EvidenceCategoryValue] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class EvidenceCategoryCollection(BaseModel):
    categories: List[EvidenceCategory]

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ChecklistStatusResponse(BaseModel):
    checklist_status: str = Field(
        ...,
        serialization_alias="checklistStatus",
        validation_alias=AliasChoices("checklistStatus", "checklist_status"),
    )
    status_message: Optional[str] = Field(
        default=None,
        serialization_alias="statusMessage",
        validation_alias=AliasChoices("statusMessage", "status_message"),
    )
    phase: Optional[str] = Field(
        default=None,
        serialization_alias="phase",
        validation_alias=AliasChoices("phase",),
    )
    slurm_state: Optional[str] = Field(
        default=None,
        serialization_alias="slurmState",
        validation_alias=AliasChoices("slurmState", "slurm_state"),
    )
    current_step: Optional[int] = Field(
        default=None,
        serialization_alias="currentStep",
        validation_alias=AliasChoices("currentStep", "current_step"),
    )
    max_steps: Optional[int] = Field(
        default=None,
        serialization_alias="maxSteps",
        validation_alias=AliasChoices("maxSteps", "max_steps"),
    )
    error: Optional[str] = Field(
        default=None,
        serialization_alias="error",
        validation_alias=AliasChoices("error",),
    )
    document_checklists: Optional[EvidenceCollection] = Field(
        default=None,
        serialization_alias="documentChecklists",
        validation_alias=AliasChoices("documentChecklists", "document_checklists"),
    )

    model_config = ConfigDict(extra="forbid", populate_by_name=True)
