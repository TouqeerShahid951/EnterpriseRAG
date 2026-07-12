"""Public evaluation repository dependency."""

from __future__ import annotations

from functools import lru_cache

from ..core.config import settings
from .evaluation_memory import InMemoryEvaluationRepository
from .evaluation_models import (
    EvaluationCaseResultRecord,
    EvaluationDatasetRecord,
    EvaluationRepository,
    EvaluationRunRecord,
)
from .evaluation_postgres import (
    EVALUATION_SCHEMA_SQL,
    PostgresEvaluationRepository,
    case_result_from_row,
    dataset_from_row,
    run_from_row,
)


@lru_cache
def default_evaluation_repository() -> EvaluationRepository:
    if settings.document_repository == "memory":
        return InMemoryEvaluationRepository()
    return PostgresEvaluationRepository(settings.database_url)


def get_evaluation_repository() -> EvaluationRepository:
    return default_evaluation_repository()


__all__ = [
    "EVALUATION_SCHEMA_SQL",
    "EvaluationCaseResultRecord",
    "EvaluationDatasetRecord",
    "EvaluationRepository",
    "EvaluationRunRecord",
    "InMemoryEvaluationRepository",
    "PostgresEvaluationRepository",
    "case_result_from_row",
    "dataset_from_row",
    "default_evaluation_repository",
    "get_evaluation_repository",
    "run_from_row",
]
