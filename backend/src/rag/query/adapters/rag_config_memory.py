"""In-memory workspace RAG configuration repository."""

from __future__ import annotations

from ..rag_config_models import RagConfigRecord
from ..rag_config_validation import with_updated_at


class InMemoryRagConfigRepository:
    def __init__(self) -> None:
        self.active: RagConfigRecord | None = None

    def get_active(self) -> RagConfigRecord | None:
        return self.active

    def save_active(self, config: RagConfigRecord) -> RagConfigRecord:
        saved = with_updated_at(config)
        self.active = saved
        return saved
