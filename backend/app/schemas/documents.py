from __future__ import annotations

from typing import List, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from .checklists import EvidenceCollection


class DocumentMetadata(BaseModel):
    id: int = Field(..., description="Stable identifier for the document")
    title: str = Field(..., description="Human-readable title for display")
    type: Optional[str] = Field(None, description="Document type or classifier label")
    description: Optional[str] = None
    source: Optional[str] = Field(None, description="Where the document was obtained from")
    court: Optional[str] = Field(None, description="Court associated with the document")
    state: Optional[str] = Field(None, description="State associated with the document")
    ecf_number: Optional[str] = Field(
        None,
        description="Docket/ECF number for ordering",
        serialization_alias="ecfNumber",
        validation_alias=AliasChoices("ecf_number", "ecfNumber"),
    )
    file_url: Optional[str] = Field(
        None,
        description="Source file URL",
        serialization_alias="fileUrl",
        validation_alias=AliasChoices("fileUrl", "file_url"),
    )
    external_url: Optional[str] = Field(
        None,
        description="External URL for the document",
        serialization_alias="externalUrl",
        validation_alias=AliasChoices("externalUrl", "external_url"),
    )
    clearinghouse_link: Optional[str] = Field(
        None,
        description="Clearinghouse document URL",
        serialization_alias="clearinghouseLink",
        validation_alias=AliasChoices("clearinghouseLink", "clearinghouse_link"),
    )
    text_url: Optional[str] = Field(
        None,
        description="Clearinghouse text URL",
        serialization_alias="textUrl",
        validation_alias=AliasChoices("textUrl", "text_url"),
    )
    date: Optional[str] = Field(
        None,
        description="Filing or decision date (ISO)",
    )
    date_is_estimate: Optional[bool] = Field(
        None,
        description="Whether the filing date is an estimate",
        serialization_alias="dateIsEstimate",
        validation_alias=AliasChoices("dateIsEstimate", "date_is_estimate"),
    )
    date_not_available: Optional[bool] = Field(
        None,
        description="Date missing flag from source",
        serialization_alias="dateNotAvailable",
        validation_alias=AliasChoices("dateNotAvailable", "date_not_available"),
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


class DocumentListResponse(BaseModel):
    case_id: str
    documents: List[Document]
    document_checklists: Optional[EvidenceCollection] = Field(
        default=None,
        serialization_alias="documentChecklists",
        validation_alias=AliasChoices("documentChecklists", "document_checklists"),
    )
    checklist_status: str = Field(
        default="idle",
        serialization_alias="checklistStatus",
        validation_alias=AliasChoices("checklistStatus", "checklist_status"),
    )
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


class UploadDocumentsResponse(BaseModel):
    case_id: str = Field(
        ...,
        serialization_alias="caseId",
        validation_alias=AliasChoices("caseId", "case_id"),
    )
    reused: bool
    document_count: int = Field(
        ...,
        serialization_alias="documentCount",
        validation_alias=AliasChoices("documentCount", "document_count"),
    )
    signature: str
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
    case_name: str = Field(
        ...,
        serialization_alias="caseName",
        validation_alias=AliasChoices("caseName", "case_name"),
        min_length=1,
    )
    documents: List[UploadManifestDocument] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)
