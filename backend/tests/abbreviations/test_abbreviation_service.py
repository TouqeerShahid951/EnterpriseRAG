from uuid import uuid4

import pytest

from rag.abbreviations.adapters.memory import InMemoryAbbreviationRepository
from rag.abbreviations.service import (
    AbbreviationGlossaryRejected,
    AbbreviationGlossaryService,
)
from rag.auth.identity_models import UserRecord


def test_global_admin_can_create_edit_and_delete_an_entry() -> None:
    repository = InMemoryAbbreviationRepository()
    service = AbbreviationGlossaryService(repository)
    actor = _user("system_admin", ())

    created = service.create_entry(
        abbreviation=" ad ",
        expansion=" Assistant   Director ",
        actor=actor,
    )
    updated = service.update_entry(
        created.id,
        abbreviation="AD",
        expansion="Associate Director",
        expected_revision=created.revision,
        actor=actor,
    )
    service.delete_entry(
        updated.id,
        expected_revision=updated.revision,
        actor=actor,
    )

    assert created.abbreviation == "AD"
    assert created.expansion == "Assistant Director"
    assert updated.expansion == "Associate Director"
    assert updated.revision == 2
    assert repository.list_entries() == []


@pytest.mark.parametrize(
    ("account_type", "group_paths", "allowed"),
    [
        ("platform_admin", (), True),
        ("system_admin", (), True),
        ("space_admin", ("/legal",), False),
        ("contributor", ("/legal",), False),
        ("reviewer", ("/legal",), False),
        ("auditor", ("/legal",), False),
        ("member", ("/legal",), False),
    ],
)
def test_only_global_admins_can_view(
    account_type: str,
    group_paths: tuple[str, ...],
    allowed: bool,
) -> None:
    service = AbbreviationGlossaryService(InMemoryAbbreviationRepository())
    actor = _user(account_type, group_paths)

    if allowed:
        assert service.view(actor=actor) == (None, [], [])
    else:
        with pytest.raises(AbbreviationGlossaryRejected) as exc_info:
            service.view(actor=actor)
        assert exc_info.value.code == "abbreviation_glossary_forbidden"


def test_duplicate_and_stale_updates_return_conflicts() -> None:
    repository = InMemoryAbbreviationRepository()
    service = AbbreviationGlossaryService(repository)
    actor = _user("platform_admin", ())
    first = service.create_entry(
        abbreviation="AD", expansion="Assistant Director", actor=actor
    )

    with pytest.raises(AbbreviationGlossaryRejected) as duplicate:
        service.create_entry(
            abbreviation="ad", expansion="Another Definition", actor=actor
        )
    assert duplicate.value.code == "abbreviation_already_exists"

    service.update_entry(
        first.id,
        abbreviation="AD",
        expansion="Associate Director",
        expected_revision=first.revision,
        actor=actor,
    )
    with pytest.raises(AbbreviationGlossaryRejected) as stale:
        service.update_entry(
            first.id,
            abbreviation="AD",
            expansion="Area Director",
            expected_revision=first.revision,
            actor=actor,
        )
    assert stale.value.code == "abbreviation_revision_conflict"


def test_import_rejects_conflicting_definitions_before_replacement() -> None:
    repository = InMemoryAbbreviationRepository()
    service = AbbreviationGlossaryService(repository)

    with pytest.raises(AbbreviationGlossaryRejected) as exc_info:
        service.import_document_entries(
            document_id=str(uuid4()),
            entries=[
                ("AD", "Assistant Director", 1),
                ("AD", "Active Directory", 2),
            ],
        )

    assert exc_info.value.code == "abbreviation_glossary_conflict"


def test_pdf_sources_merge_identical_terms_and_remove_independently() -> None:
    repository = InMemoryAbbreviationRepository()
    service = AbbreviationGlossaryService(repository)
    actor = _user("system_admin", ())

    service.import_document_entries(
        document_id="source-one",
        entries=[("AD", "Assistant Director", 1), ("DD", "Deputy Director", 2)],
    )
    service.import_document_entries(
        document_id="source-two",
        entries=[("AD", "Assistant Director", 4), ("FIA", "Federal Investigation Agency", 5)],
    )

    _glossary, sources, entries = service.view(actor=actor)
    assert {source.document_id for source in sources} == {"source-one", "source-two"}
    assert next(entry for entry in entries if entry.abbreviation == "AD").source_count == 2

    with pytest.raises(AbbreviationGlossaryRejected) as conflict:
        service.import_document_entries(
            document_id="source-three",
            entries=[("AD", "Active Directory", 1)],
        )
    assert conflict.value.code == "abbreviation_glossary_conflict"

    service.remove_source("source-one", actor=actor)

    _glossary, sources, entries = service.view(actor=actor)
    assert [source.document_id for source in sources] == ["source-two"]
    assert {entry.abbreviation for entry in entries} == {"AD", "FIA"}


def _user(account_type: str, group_paths: tuple[str, ...]) -> UserRecord:
    return UserRecord(
        id=str(uuid4()),
        email=f"{uuid4()}@example.test",
        name="Test User",
        password_hash="hash",
        is_active=True,
        account_type=account_type,  # type: ignore[arg-type]
        clearance_level="NATO_SECRET",
        must_change_password=False,
        permission_version=1,
        group_paths=group_paths,
    )
