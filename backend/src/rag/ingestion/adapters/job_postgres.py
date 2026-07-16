"""PostgreSQL ingestion-job repository."""

from __future__ import annotations

from ...shared.persistence import PostgresConnectionMixin
from ..delivery.adapters.postgres import PostgresIngestDeliveryRepositoryMixin
from .job_postgres_lifecycle import PostgresIngestJobLifecycleMixin
from .job_postgres_search import PostgresIngestJobSearchMixin


class PostgresIngestJobRepository(
    PostgresIngestDeliveryRepositoryMixin,
    PostgresIngestJobLifecycleMixin,
    PostgresIngestJobSearchMixin,
    PostgresConnectionMixin,
):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url


__all__ = ["PostgresIngestJobRepository"]
