"""In-memory abbreviation repository for tests and local memory mode."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

from ..models import (
    AbbreviationEntryRecord,
    AbbreviationGlossaryRecord,
    AbbreviationSourceRecord,
    DuplicateAbbreviationError,
    SourceAbbreviationConflictError,
    StaleAbbreviationRevisionError,
)


class InMemoryAbbreviationRepository:
    def __init__(self) -> None:
        self.entries: dict[str, AbbreviationEntryRecord] = {}
        self.sources: dict[str, AbbreviationSourceRecord] = {}
        self.entry_sources: dict[str, set[str]] = {}

    def get_glossary(self) -> AbbreviationGlossaryRecord | None:
        if not self.entries:
            return None
        ordered = sorted(
            self.entries.values(),
            key=lambda entry: entry.updated_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        latest = ordered[0]
        sources = self.list_sources()
        sourced = sources[0] if sources else None
        return AbbreviationGlossaryRecord(
            source_document_id=sourced.document_id if sourced else None,
            source_document_title=sourced.document_title if sourced else None,
            updated_at=latest.updated_at,
        )

    def list_sources(self) -> list[AbbreviationSourceRecord]:
        counts = {
            source_id: sum(source_id in source_ids for source_ids in self.entry_sources.values())
            for source_id in self.sources
        }
        return sorted(
            (replace(source, entry_count=counts[source_id]) for source_id, source in self.sources.items()),
            key=lambda source: source.activated_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

    def list_entries(self) -> list[AbbreviationEntryRecord]:
        return sorted(self.entries.values(), key=lambda entry: entry.abbreviation)

    def get_entry(self, entry_id: str) -> AbbreviationEntryRecord | None:
        return self.entries.get(entry_id)

    def create_entry(
        self,
        *,
        abbreviation: str,
        expansion: str,
        actor_id: str,
    ) -> AbbreviationEntryRecord:
        _ = actor_id
        if any(
            entry.abbreviation.casefold() == abbreviation.casefold()
            for entry in self.entries.values()
        ):
            raise DuplicateAbbreviationError(abbreviation)
        now = datetime.now(timezone.utc)
        entry = AbbreviationEntryRecord(
            id=str(uuid4()),
            abbreviation=abbreviation,
            expansion=expansion,
            source_kind="ui",
            source_document_id=None,
            source_document_title=None,
            source_page=None,
            source_count=0,
            revision=1,
            created_at=now,
            updated_at=now,
        )
        self.entries[entry.id] = entry
        return entry

    def update_entry(
        self,
        entry_id: str,
        *,
        abbreviation: str,
        expansion: str,
        expected_revision: int,
        actor_id: str,
    ) -> AbbreviationEntryRecord | None:
        _ = actor_id
        current = self.entries.get(entry_id)
        if current is None:
            return None
        if current.revision != expected_revision:
            raise StaleAbbreviationRevisionError(entry_id)
        if any(
            entry.id != entry_id
            and entry.abbreviation.casefold() == abbreviation.casefold()
            for entry in self.entries.values()
        ):
            raise DuplicateAbbreviationError(abbreviation)
        updated = replace(
            current,
            abbreviation=abbreviation,
            expansion=expansion,
            source_kind="ui",
            source_document_id=None,
            source_document_title=None,
            source_page=None,
            source_count=0,
            revision=current.revision + 1,
            updated_at=datetime.now(timezone.utc),
        )
        self.entry_sources.pop(entry_id, None)
        self.entries[entry_id] = updated
        return updated

    def delete_entry(
        self,
        entry_id: str,
        *,
        expected_revision: int,
        actor_id: str,
    ) -> bool:
        _ = actor_id
        current = self.entries.get(entry_id)
        if current is None:
            return False
        if current.revision != expected_revision:
            raise StaleAbbreviationRevisionError(entry_id)
        del self.entries[entry_id]
        self.entry_sources.pop(entry_id, None)
        return True

    def remove_source(self, document_id: str, *, actor_id: str) -> bool:
        _ = actor_id
        if self.sources.pop(document_id, None) is None:
            return False
        for entry_id, source_ids in list(self.entry_sources.items()):
            source_ids.discard(document_id)
            if source_ids:
                source_id = sorted(source_ids)[0]
                self.entries[entry_id] = replace(
                    self.entries[entry_id],
                    source_document_id=source_id,
                    source_document_title=self.sources[source_id].document_title,
                    source_count=len(source_ids),
                    updated_at=datetime.now(timezone.utc),
                )
            else:
                self.entry_sources.pop(entry_id, None)
                if self.entries[entry_id].source_kind == "pdf":
                    del self.entries[entry_id]
        return True

    def replace_from_document(self, *, document_id: str, entries) -> int:
        previous_entries = self.entries.copy()
        previous_sources = self.sources.copy()
        previous_entry_sources = {
            entry_id: set(source_ids)
            for entry_id, source_ids in self.entry_sources.items()
        }
        self.remove_source(document_id, actor_id="")
        now = datetime.now(timezone.utc)
        self.sources[document_id] = AbbreviationSourceRecord(
            document_id=document_id,
            document_title=document_id,
            entry_count=0,
            activated_at=now,
        )
        for abbreviation, expansion, source_page in entries:
            existing = next(
                (entry for entry in self.entries.values() if entry.abbreviation.casefold() == abbreviation.casefold()),
                None,
            )
            if existing is not None:
                if existing.source_kind != "pdf" or existing.expansion.casefold() != expansion.casefold():
                    self.entries = previous_entries
                    self.sources = previous_sources
                    self.entry_sources = previous_entry_sources
                    raise SourceAbbreviationConflictError(abbreviation)
                source_ids = self.entry_sources.setdefault(existing.id, set())
                source_ids.add(document_id)
                self.entries[existing.id] = replace(
                    existing,
                    source_count=len(source_ids),
                    updated_at=now,
                )
                continue
            entry = AbbreviationEntryRecord(
                id=str(uuid4()),
                abbreviation=abbreviation,
                expansion=expansion,
                source_kind="pdf",
                source_document_id=document_id,
                source_document_title=document_id,
                source_page=source_page,
                source_count=1,
                revision=1,
                created_at=now,
                updated_at=now,
            )
            self.entries[entry.id] = entry
            self.entry_sources[entry.id] = {document_id}
        return len(entries)

    def find_entries(self, abbreviations, *, query) -> list[AbbreviationEntryRecord]:
        requested = {value.casefold() for value in abbreviations}
        normalized_query = " ".join(query.casefold().split())
        return [
            entry
            for entry in self.entries.values()
            if entry.abbreviation.casefold() in requested
            or entry.expansion.casefold() in normalized_query
        ]
