"""Application behavior for the Document Library overview."""

from dataclasses import replace
from datetime import date, timedelta

from rag.auth.abac import normalize_group_path
from rag.auth.document_access import can_read_document
from rag.auth.identity_models import UserRecord
from rag.auth.permissions import can_read_document_metadata, is_global_admin
from rag.shared.contracts.abbreviations import ABBREVIATION_GLOSSARY_DOC_TYPE
from rag.shared.contracts.clearance import clearance_levels_at_or_below

from rag.ingestion.job_models import IngestJobRepository

from .models import DocumentOverviewSnapshot, DocumentRepository


EXPIRING_SOON_DAYS = 30


def build_document_overview(
    *,
    user: UserRecord,
    repository: DocumentRepository,
    today: date | None = None,
    job_repository: IngestJobRepository | None = None,
) -> DocumentOverviewSnapshot:
    """Return the visible document-health snapshot for one user."""

    if not can_read_document_metadata(user):
        return DocumentOverviewSnapshot()
    start = today or date.today()
    group_paths = (
        None
        if is_global_admin(user)
        else tuple(sorted({normalize_group_path(path) for path in user.group_paths}))
    )
    overview = repository.summarize_document_overview(
        clearance_levels=clearance_levels_at_or_below(user.clearance_level),
        group_paths=group_paths,
        expiring_from=start,
        expiring_to=start + timedelta(days=EXPIRING_SOON_DAYS),
        attention_limit=5,
        exclude_abbreviation_glossary=True,
    )
    glossary_trash = sum(
        document.doc_type == ABBREVIATION_GLOSSARY_DOC_TYPE
        and can_read_document(user, document)
        for document in repository.list_documents(state="deleted")
    )
    jobs = tuple(
        job
        for document in overview.attention_documents
        if job_repository is not None
        if (job := job_repository.get_latest_ingest_job_for_document(
            document.id,
            statuses=frozenset({"scheduled", "queued", "processing", "human_review", "complete", "failed", "cancelled"}),
        )) is not None
    )
    return replace(overview, trash=overview.trash + glossary_trash, attention_jobs=jobs)
