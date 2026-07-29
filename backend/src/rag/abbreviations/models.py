"""Domain records and persistence contract for managed abbreviations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, Sequence


@dataclass(frozen=True, slots=True)
class AbbreviationEntryRecord:
    id: str
    abbreviation: str
    expansion: str
    source_kind: str
    source_document_id: str | None
    source_document_title: str | None
    source_page: int | None
    source_count: int
    revision: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AbbreviationGlossaryRecord:
    source_document_id: str | None
    source_document_title: str | None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AbbreviationSourceRecord:
    document_id: str
    document_title: str
    entry_count: int
    activated_at: datetime | None = None


class AbbreviationRepository(Protocol):
    def get_glossary(self) -> AbbreviationGlossaryRecord | None: ...

    def list_sources(self) -> list[AbbreviationSourceRecord]: ...

    def list_entries(self) -> list[AbbreviationEntryRecord]: ...

    def get_entry(self, entry_id: str) -> AbbreviationEntryRecord | None: ...

    def create_entry(
        self,
        *,
        abbreviation: str,
        expansion: str,
        actor_id: str,
    ) -> AbbreviationEntryRecord: ...

    def update_entry(
        self,
        entry_id: str,
        *,
        abbreviation: str,
        expansion: str,
        expected_revision: int,
        actor_id: str,
    ) -> AbbreviationEntryRecord | None: ...

    def delete_entry(
        self,
        entry_id: str,
        *,
        expected_revision: int,
        actor_id: str,
    ) -> bool: ...

    def remove_source(self, document_id: str, *, actor_id: str) -> bool: ...

    def replace_from_document(
        self,
        *,
        document_id: str,
        entries: Sequence[tuple[str, str, int | None]],
    ) -> int: ...

    def find_entries(
        self,
        abbreviations: Sequence[str],
        *,
        query: str,
    ) -> list[AbbreviationEntryRecord]: ...


class DuplicateAbbreviationError(ValueError):
    """Raised when the global glossary already contains an abbreviation."""


class StaleAbbreviationRevisionError(ValueError):
    """Raised when an entry changed after the client loaded it."""


class SourceAbbreviationConflictError(ValueError):
    """Raised when a PDF source conflicts with an active definition."""
