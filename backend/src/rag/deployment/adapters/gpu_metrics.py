"""Sample visible NVIDIA devices with the driver-provided utility."""

import csv
import io
import math
import subprocess

from rag.deployment.resource_metrics import GpuDevice, GpuSnapshot


def _number(value: str) -> float | None:
    value = value.strip()
    if value in {"N/A", "[N/A]", "[Not Supported]", "Not Supported"}:
        return None
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Non-finite GPU counter")
    return number


def _bytes(value: str) -> int | None:
    number = _number(value)
    return None if number is None else int(number * 1024 ** 2)


def read_gpu_metrics() -> GpuSnapshot:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=uuid,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=True, timeout=2,
        )
        devices = []
        for row in csv.reader(io.StringIO(result.stdout), skipinitialspace=True):
            identifier, name, utilization, used, total, temperature, power = row
            if not identifier.strip() or not name.strip():
                raise ValueError("Missing GPU identity")
            devices.append(GpuDevice(
                id=identifier.strip(), name=name.strip(), utilization_percent=_number(utilization),
                memory_used_bytes=_bytes(used), memory_total_bytes=_bytes(total),
                temperature_c=_number(temperature), power_watts=_number(power),
            ))
        return GpuSnapshot(devices=devices, unavailable_reason=None if devices else "No NVIDIA GPUs are visible to this runtime.")
    except FileNotFoundError:
        reason = "NVIDIA telemetry is unavailable. Docker on Mac cannot expose the Apple GPU; Windows NVIDIA deployments require GPU passthrough."
    except subprocess.TimeoutExpired:
        reason = "GPU sampling timed out. Check the NVIDIA driver and container GPU access."
    except (OSError, subprocess.CalledProcessError):
        reason = "NVIDIA telemetry could not be read. Check the driver and container GPU access."
    except (ValueError, csv.Error):
        reason = "NVIDIA telemetry returned invalid counters."
    return GpuSnapshot(unavailable_reason=reason)
