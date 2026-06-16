"""Celery application for ingestion tasks."""

from __future__ import annotations

from celery import Celery

from rag_ingestion.config import WorkerConfig

config = WorkerConfig.from_env()
celery_app = Celery("rag-ingestion-worker", broker=config.redis_url, include=["apps.ingestion.tasks"])
celery_app.conf.update(
    task_default_queue=config.ingest_queue_name,
    task_serializer="json",
    accept_content=["json"],
    result_backend=None,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    broker_transport_options={"visibility_timeout": 21600},
    worker_concurrency=config.worker_boot_concurrency,
    worker_max_tasks_per_child=1,
    task_soft_time_limit=7200,
    task_time_limit=7500,
)
app = celery_app
