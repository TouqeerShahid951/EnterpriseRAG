"""Celery application for artifact-generation jobs."""

from celery import Celery

from rag.core.config import settings


celery_app = Celery(
    "artifact-generation-worker",
    broker=settings.celery_broker_url or settings.redis_url,
    include=["apps.workers.artifact.tasks"],
)
celery_app.conf.update(
    task_default_queue=settings.artifact_queue_name,
    task_serializer="json",
    accept_content=["json"],
    result_backend=None,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    broker_transport_options={"visibility_timeout": 7200},
    worker_concurrency=1,
    worker_max_tasks_per_child=10,
    task_soft_time_limit=int(settings.artifact_worker_timeout_seconds),
    task_time_limit=int(settings.artifact_worker_timeout_seconds + 60),
)
app = celery_app
