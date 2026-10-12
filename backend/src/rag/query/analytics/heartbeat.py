"""Keep an execution observable during blocking retrieval, generation and streaming."""

from contextlib import contextmanager
import logging
from threading import Event, Thread

from .models import AnalyticsExecutionRepository

logger = logging.getLogger(__name__)


@contextmanager
def execution_heartbeat(repository: AnalyticsExecutionRepository, execution_id: str, *, grace_seconds: int):
    if grace_seconds < 1:
        raise ValueError("grace_seconds must be positive")
    stopped = Event()
    interval = min(30.0, grace_seconds / 3)

    def beat():
        while not stopped.wait(interval):
            try:
                if not repository.heartbeat_execution(execution_id, grace_seconds=grace_seconds):
                    return
            except Exception:  # noqa: BLE001 - an analytics outage cannot cancel a query
                logger.warning("query analytics heartbeat failed")

    # ponytail: one daemon thread per active execution, as in evaluation heartbeats;
    # batch per process only if measured concurrent-query overhead warrants it.
    thread = Thread(target=beat, name="query-analytics-heartbeat", daemon=True)
    try:
        thread.start()
    except Exception:  # noqa: BLE001 - retain fail-open query behavior
        logger.warning("query analytics heartbeat could not start")
        yield
        return
    try:
        yield
    finally:
        stopped.set()
        thread.join(timeout=1)
