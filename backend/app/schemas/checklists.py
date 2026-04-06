from __future__ import annotations

from typing import List, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

SUMMARY_DOCUMENT_ID = -1


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
