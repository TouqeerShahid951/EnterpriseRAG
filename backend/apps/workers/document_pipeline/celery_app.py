"""Celery application shared by ingestion and GraphRAG workers."""

from __future__ import annotations

import os

from celery import Celery

from rag.ingestion.config import WorkerConfig
from rag.shared.contracts.task_names import (
    DEFAULT_GRAPHRAG_INDEX_TASK_NAME,
    DEFAULT_GRAPHRAG_PARTITION_REBUILD_TASK_NAME,
)

config = WorkerConfig.from_env()
soft_time_limit = int(os.getenv("INGEST_TASK_SOFT_TIME_LIMIT_SECONDS", "1800"))
hard_time_limit = int(os.getenv("INGEST_TASK_TIME_LIMIT_SECONDS", str(soft_time_limit + 120)))
celery_app = Celery(
    "rag-ingestion-worker",
    broker=config.redis_url,
    include=["apps.workers.document_pipeline.tasks"],
)
graphrag_task_names = {
    DEFAULT_GRAPHRAG_INDEX_TASK_NAME,
    DEFAULT_GRAPHRAG_PARTITION_REBUILD_TASK_NAME,
    config.graphrag_index_task_name,
    config.graphrag_partition_rebuild_task_name,
}
celery_app.conf.update(
    task_default_queue=config.ingest_queue_name,
    task_routes={
        name: {"queue": config.graphrag_queue_name}
        for name in graphrag_task_names
    },
    task_serializer="json",
    accept_content=["json"],
    result_backend=None,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    broker_transport_options={"visibility_timeout": 21600},
    worker_concurrency=config.worker_boot_concurrency,
    worker_max_tasks_per_child=1,
    task_soft_time_limit=soft_time_limit,
    task_time_limit=hard_time_limit,
)
app = celery_app
