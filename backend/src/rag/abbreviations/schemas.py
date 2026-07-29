"""HTTP schemas for abbreviation glossary administration and import."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class AbbreviationEntry(BaseModel):
    id: str
    abbreviation: str
    expansion: str
    source_kind: str
    source_document_id: str | None = None
    source_document_title: str | None = None
    source_page: int | None = None
    source_count: int = Field(default=0, ge=0)
    revision: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AbbreviationGlossary(BaseModel):
    source_document_id: str | None = None
    source_document_title: str | None = None
    updated_at: datetime | None = None


class AbbreviationSource(BaseModel):
    document_id: str
    document_title: str
    entry_count: int = Field(ge=0)
    activated_at: datetime | None = None


class AbbreviationGlossaryResponse(BaseModel):
    glossary: AbbreviationGlossary | None = None
    sources: list[AbbreviationSource] = Field(default_factory=list)
    items: list[AbbreviationEntry] = Field(default_factory=list)


class AbbreviationEntryCreateRequest(BaseModel):
    abbreviation: str
    expansion: str


class AbbreviationEntryUpdateRequest(BaseModel):
    abbreviation: str
    expansion: str
    expected_revision: int = Field(ge=1)


class AbbreviationImportEntry(BaseModel):
    abbreviation: str
    expansion: str
    source_page: int | None = Field(default=None, ge=1)


class AbbreviationImportRequest(BaseModel):
    document_id: UUID
    entries: list[AbbreviationImportEntry]


class AbbreviationImportResponse(BaseModel):
    imported_count: int
