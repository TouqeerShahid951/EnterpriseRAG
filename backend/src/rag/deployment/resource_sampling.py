"""Keep one recent resource sample independently of dashboard request volume."""

import logging
from threading import Event, Lock, Thread
import time

from .resource_metrics import ResourceReader, ResourceSnapshot

logger = logging.getLogger(__name__)


class ResourceSampleUnavailable(Exception):
    """No sufficiently recent sample is available."""


class ResourceSampler:
    # ponytail: one sampler per API process; share externally if replica count makes sampling costly.
    def __init__(self, reader: ResourceReader, *, interval_seconds: float = 2, max_age_seconds: float = 10):
        if interval_seconds <= 0 or max_age_seconds <= interval_seconds:
            raise ValueError("Sample age must exceed a positive sampling interval")
        self._reader = reader
        self._interval = interval_seconds
        self._max_age = max_age_seconds
        self._sample: ResourceSnapshot | None = None
        self._sample_started = 0.0
        self._lock = Lock()
        self._stopped = Event()
        self._thread = Thread(target=self._run, name="resource-sampler", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()
        self._thread.join(timeout=3)
        if self._thread.is_alive():
            logger.warning("Resource sampler did not stop within its shutdown deadline")

    def read(self) -> ResourceSnapshot:
        with self._lock:
            if self._sample is None or time.monotonic() - self._sample_started > self._max_age:
                raise ResourceSampleUnavailable("Resource telemetry is starting or temporarily unavailable.")
            return self._sample

    def _run(self) -> None:
        while not self._stopped.is_set():
            started = time.monotonic()
            try:
                sample = self._reader.read()
            except Exception:  # noqa: BLE001 - keep telemetry failures isolated and retry on the next cycle
                logger.warning("Resource sampling failed; the previous sample will expire")
            else:
                with self._lock:
                    self._sample = sample
                    self._sample_started = started
            # No overlapping work or catch-up bursts when a device is slow.
            if self._stopped.wait(self._interval):
                break
