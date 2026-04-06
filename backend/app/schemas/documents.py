from __future__ import annotations

from typing import List, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class DocumentMetadata(BaseModel):
    id: int = Field(..., description="Stable identifier for the document")
    title: str = Field(..., description="Human-readable title for display")
    type: Optional[str] = Field(None, description="Document type or classifier label")
    description: Optional[str] = None
    source: Optional[str] = Field(None, description="Where the document was obtained from")
    ecf_number: Optional[str] = Field(
        None,
        description="Docket/ECF number for ordering",
        serialization_alias="ecfNumber",
        validation_alias=AliasChoices("ecf_number", "ecfNumber"),
    )
    date: Optional[str] = Field(
        None,
        description="Filing or decision date (ISO)",
    )
    is_docket: bool = Field(
        False,
        description="True when representing the main docket and should be ordered first",
        serialization_alias="isDocket",
        validation_alias=AliasChoices("isDocket", "is_docket"),
    )
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Document(DocumentMetadata):
    content: str = Field(..., description="Full document body as plain text")
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class DocumentReference(BaseModel):
    id: int
    title: Optional[str] = Field(None, description="Display title when overriding stored metadata")
    type: Optional[str] = Field(None, description="Document type or classifier label")
    alias: Optional[str] = Field(None, description="Optional alternate name to show in prompts")
    include_full_text: bool = Field(False, description="If true, use client-provided content instead of repository lookup")
    content: Optional[str] = Field(None, description="Raw document text supplied by the caller")
    date: Optional[str] = Field(
        None,
        description="Filing or decision date (ISO)",
    )
    ecf_number: Optional[str] = Field(
        None,
        serialization_alias="ecfNumber",
        validation_alias=AliasChoices("ecf_number", "ecfNumber"),
    )
    is_docket: bool = Field(
        False,
        serialization_alias="isDocket",
        validation_alias=AliasChoices("isDocket", "is_docket"),
    )
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class DocumentChunk(BaseModel):
    id: str
    text: str
    start: int
    end: int
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class UploadManifestDocument(BaseModel):
    name: str = Field(..., min_length=1, description="Display document name")
    date: Optional[str] = Field(
        None,
        description="Filing or decision date (ISO)",
    )
    type: str = Field(..., min_length=1, description="Document type selection")
    type_other: Optional[str] = Field(
        None,
        serialization_alias="typeOther",
        validation_alias=AliasChoices("typeOther", "type_other"),
        description="Custom document type when type is Other",
    )
    file_name: Optional[str] = Field(
        None,
        serialization_alias="fileName",
        validation_alias=AliasChoices("fileName", "file_name"),
        description="Original filename provided by the client",
    )

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class UploadDocumentsManifest(BaseModel):
    title: str = Field(..., min_length=1)
    documents: List[UploadManifestDocument] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)
