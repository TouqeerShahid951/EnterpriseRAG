"""Match source lookups to an expected document revision without replacing evidence."""

from dataclasses import dataclass
from datetime import date
from hashlib import sha256

from .models import DocumentRecord


@dataclass(frozen=True)
class SourceRevision:
    generation_id: str | None = None
    content_hash: str | None = None

    def matches(self, document: DocumentRecord) -> bool:
        return bool(
            document.is_current
            and document.deleted_at is None
            and (document.expiry_date is None or document.expiry_date >= date.today())
            and (
                self.generation_id is None
                or self.generation_id == document.active_index_generation_id
            )
            and (
                self.content_hash is None or self.content_hash == document.content_hash
            )
        )

    def matches_content(self, content: bytes) -> bool:
        return (
            self.content_hash is None
            or sha256(content).hexdigest() == self.content_hash
        )
