"""Application behavior for the Document Library overview."""

from datetime import date, timedelta

from rag.auth.abac import normalize_group_path
from rag.auth.identity_models import UserRecord
from rag.auth.permissions import can_read_document_metadata, is_global_admin
from rag.shared.contracts.clearance import clearance_levels_at_or_below

from .models import DocumentOverviewSnapshot, DocumentRepository


EXPIRING_SOON_DAYS = 30


def build_document_overview(
    *,
    user: UserRecord,
    repository: DocumentRepository,
    today: date | None = None,
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
    return repository.summarize_document_overview(
        clearance_levels=clearance_levels_at_or_below(user.clearance_level),
        group_paths=group_paths,
        expiring_from=start,
        expiring_to=start + timedelta(days=EXPIRING_SOON_DAYS),
        attention_limit=5,
    )
