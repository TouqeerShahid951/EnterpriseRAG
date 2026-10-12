"""Collect bounded, read-only OS metrics without extra runtime dependencies."""

from datetime import UTC, datetime
from pathlib import Path
import shutil

from rag.deployment.adapters.gpu_metrics import read_gpu_metrics
from rag.deployment.resource_metrics import ResourceMetric, ResourceSnapshot


def cpu_totals(text: str) -> tuple[int, int]:
    # Linux guest counters are already included in user/nice; do not count twice.
    values = [int(value) for value in text.splitlines()[0].split()[1:9]]
    if len(values) < 4 or any(value < 0 for value in values):
        raise ValueError("Invalid CPU counters")
    return sum(values), values[3] + (values[4] if len(values) > 4 else 0)


class OsResourceReader:
    def __init__(self):
        self._previous_cpu: tuple[int, int] | None = None

    def read(self) -> ResourceSnapshot:
        metrics = []
        for label, scope, collect in (
            ("CPU", "Linux host / Docker VM · average since previous sample", self._cpu),
            ("Memory", "Linux host / Docker VM · includes other workloads", self._memory),
            ("Disk", "Filesystem containing the API runtime · shared capacity", self._disk),
        ):
            try:
                metrics.append(ResourceMetric(label=label, scope=scope, **collect()))
            except (OSError, ValueError, KeyError, IndexError, ZeroDivisionError):
                metrics.append(ResourceMetric(
                    label=label, scope=scope,
                    unavailable_reason="OS counters unavailable or unreadable on this runtime.",
                ))
        return ResourceSnapshot(sampled_at=datetime.now(UTC), metrics=metrics, gpu=read_gpu_metrics())

    def _cpu(self) -> dict:
        last, idle_last = cpu_totals(Path("/proc/stat").read_text())
        previous = self._previous_cpu
        self._previous_cpu = (last, idle_last)
        if previous is None:
            return {"percent": None, "unavailable_reason": "Waiting for the next CPU sample."}
        first, idle_first = previous
        if last <= first or idle_last < idle_first:
            raise ValueError("CPU counters did not advance")
        return {"percent": max(0, min(100, 100 * (1 - (idle_last - idle_first) / (last - first))))}

    @staticmethod
    def _memory() -> dict:
        values = {line.split(":")[0]: int(line.split()[1]) * 1024 for line in Path("/proc/meminfo").read_text().splitlines()}
        total = values["MemTotal"]
        used = total - values["MemAvailable"]
        return {"percent": 100 * used / total, "used_bytes": used, "total_bytes": total}

    @staticmethod
    def _disk() -> dict:
        total, used, _ = shutil.disk_usage("/")
        return {"percent": 100 * used / total, "used_bytes": used, "total_bytes": total}
