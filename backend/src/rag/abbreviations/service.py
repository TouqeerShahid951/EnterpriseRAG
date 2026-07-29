"""Application workflows for abbreviation glossary administration and lookup."""

from __future__ import annotations

from collections.abc import Sequence

from rag.auth.identity_models import UserRecord
from rag.auth.permissions import is_global_admin
from rag.shared.contracts.abbreviations import normalize_abbreviation_entry

from .models import (
    AbbreviationEntryRecord,
    AbbreviationGlossaryRecord,
    AbbreviationRepository,
    AbbreviationSourceRecord,
    DuplicateAbbreviationError,
    SourceAbbreviationConflictError,
    StaleAbbreviationRevisionError,
)


class AbbreviationGlossaryRejected(ValueError):
    def __init__(self, category: str, code: str, message: str) -> None:
        super().__init__(message)
        self.category = category
        self.code = code
        self.message = message


class AbbreviationGlossaryService:
    def __init__(self, repository: AbbreviationRepository) -> None:
        self.repository = repository

    def view(
        self,
        *,
        actor: UserRecord,
    ) -> tuple[
        AbbreviationGlossaryRecord | None,
        list[AbbreviationSourceRecord],
        list[AbbreviationEntryRecord],
    ]:
        self._require_manager(actor)
        return (
            self.repository.get_glossary(),
            self.repository.list_sources(),
            self.repository.list_entries(),
        )

    def create_entry(
        self,
        *,
        abbreviation: str,
        expansion: str,
        actor: UserRecord,
    ) -> AbbreviationEntryRecord:
        self._require_manager(actor)
        normalized_abbreviation, normalized_expansion = self._normalize(
            abbreviation, expansion
        )
        try:
            return self.repository.create_entry(
                abbreviation=normalized_abbreviation,
                expansion=normalized_expansion,
                actor_id=actor.id,
            )
        except DuplicateAbbreviationError as exc:
            raise self._duplicate(normalized_abbreviation) from exc

    def update_entry(
        self,
        entry_id: str,
        *,
        abbreviation: str,
        expansion: str,
        expected_revision: int,
        actor: UserRecord,
    ) -> AbbreviationEntryRecord:
        current = self.repository.get_entry(entry_id)
        if current is None:
            raise self._not_found()
        self._require_manager(actor)
        normalized_abbreviation, normalized_expansion = self._normalize(
            abbreviation, expansion
        )
        try:
            updated = self.repository.update_entry(
                entry_id,
                abbreviation=normalized_abbreviation,
                expansion=normalized_expansion,
                expected_revision=expected_revision,
                actor_id=actor.id,
            )
        except DuplicateAbbreviationError as exc:
            raise self._duplicate(normalized_abbreviation) from exc
        except StaleAbbreviationRevisionError as exc:
            raise self._stale() from exc
        if updated is None:
            raise self._not_found()
        return updated

    def delete_entry(
        self,
        entry_id: str,
        *,
        expected_revision: int,
        actor: UserRecord,
    ) -> None:
        current = self.repository.get_entry(entry_id)
        if current is None:
            raise self._not_found()
        self._require_manager(actor)
        try:
            deleted = self.repository.delete_entry(
                entry_id,
                expected_revision=expected_revision,
                actor_id=actor.id,
            )
        except StaleAbbreviationRevisionError as exc:
            raise self._stale() from exc
        if not deleted:
            raise self._not_found()

    def remove_source(self, document_id: str, *, actor: UserRecord) -> None:
        self._require_manager(actor)
        if not self.repository.remove_source(document_id, actor_id=actor.id):
            raise AbbreviationGlossaryRejected(
                "not_found",
                "abbreviation_source_not_found",
                "Abbreviation PDF source was not found.",
            )

    def import_document_entries(
        self,
        *,
        document_id: str,
        entries: Sequence[tuple[str, str, int | None]],
    ) -> int:
        normalized: dict[str, tuple[str, int | None]] = {}
        for abbreviation, expansion, source_page in entries:
            key, value = self._normalize(abbreviation, expansion)
            previous = normalized.get(key)
            if previous is not None and previous[0].casefold() != value.casefold():
                raise AbbreviationGlossaryRejected(
                    "invalid",
                    "abbreviation_glossary_conflict",
                    f"Glossary contains conflicting definitions for {key}.",
                )
            normalized.setdefault(key, (value, source_page))
        if not normalized:
            raise AbbreviationGlossaryRejected(
                "invalid",
                "abbreviation_glossary_empty",
                "Glossary contains no usable abbreviation entries.",
            )
        try:
            return self.repository.replace_from_document(
                document_id=document_id,
                entries=[
                    (abbreviation, expansion, source_page)
                    for abbreviation, (expansion, source_page) in normalized.items()
                ],
            )
        except SourceAbbreviationConflictError as exc:
            raise AbbreviationGlossaryRejected(
                "conflict",
                "abbreviation_glossary_conflict",
                str(exc),
            ) from exc
        except ValueError as exc:
            raise AbbreviationGlossaryRejected(
                "not_found",
                "abbreviation_glossary_document_not_found",
                str(exc),
            ) from exc

    def query_entries(
        self,
        abbreviations: Sequence[str],
        *,
        query: str,
    ) -> list[AbbreviationEntryRecord]:
        # ponytail: glossary scans are cheap at current size; add indexed alias
        # search only if query profiling shows this lookup matters.
        return self.repository.find_entries(
            abbreviations,
            query=" ".join(query.split()),
        )

    @staticmethod
    def _normalize(abbreviation: str, expansion: str) -> tuple[str, str]:
        try:
            return normalize_abbreviation_entry(abbreviation, expansion)
        except ValueError as exc:
            raise AbbreviationGlossaryRejected(
                "invalid",
                "abbreviation_entry_invalid",
                "Use a 2–20 character uppercase abbreviation and a definition up to 240 characters.",
            ) from exc

    @staticmethod
    def _require_manager(actor: UserRecord) -> None:
        if not is_global_admin(actor):
            raise AbbreviationGlossaryRejected(
                "forbidden",
                "abbreviation_glossary_forbidden",
                "Only platform and system administrators can manage the global abbreviation glossary.",
            )

    @staticmethod
    def _duplicate(abbreviation: str) -> AbbreviationGlossaryRejected:
        return AbbreviationGlossaryRejected(
            "conflict",
            "abbreviation_already_exists",
            f"{abbreviation} already exists in the global glossary.",
        )

    @staticmethod
    def _stale() -> AbbreviationGlossaryRejected:
        return AbbreviationGlossaryRejected(
            "conflict",
            "abbreviation_revision_conflict",
            "This entry changed after you loaded it. Refresh and try again.",
        )

    @staticmethod
    def _not_found() -> AbbreviationGlossaryRejected:
        return AbbreviationGlossaryRejected(
            "not_found",
            "abbreviation_not_found",
            "Abbreviation entry was not found.",
        )
