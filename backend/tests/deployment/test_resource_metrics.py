"""Resource sampling, partial failure, and administrator transport contract."""

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from rag.auth.dependencies import require_platform_admin_user
from rag.deployment.adapters.resource_metrics import OsResourceReader, cpu_totals
from rag.deployment.dependencies import get_resource_reader
from rag.deployment.routes import router


def test_resource_samples_and_partial_failure(monkeypatch):
    reader = OsResourceReader()
    monkeypatch.setattr(reader, "_cpu", lambda: {"percent": 25})
    monkeypatch.setattr(reader, "_memory", lambda: {"percent": 50, "used_bytes": 512, "total_bytes": 1024})
    def unavailable():
        raise OSError("private filesystem detail")
    monkeypatch.setattr(reader, "_disk", unavailable)
    assert cpu_totals("cpu 10 20 30 40 5 6 7 8 100 200") == (126, 45)
    snapshot = reader.read()
    assert [metric.percent for metric in snapshot.metrics] == [25, 50, None]
    assert "private" not in snapshot.model_dump_json()

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_resource_reader] = lambda: reader
    app.dependency_overrides[require_platform_admin_user] = lambda: object()
    client = TestClient(app)
    response = client.get("/api/v1/admin/system-resources")
    assert response.status_code == 200
    assert response.json()["metrics"][1]["total_bytes"] == 1024
    def forbidden():
        raise HTTPException(status_code=403)
    app.dependency_overrides[require_platform_admin_user] = forbidden
    assert client.get("/api/v1/admin/system-resources").status_code == 403
    assert "/api/v1/admin/system-resources" in app.openapi()["paths"]


def test_cpu_delta_and_memory_units(monkeypatch):
    from pathlib import Path

    samples = iter(["cpu 10 0 10 80 0 0 0 0", "cpu 20 0 20 100 0 0 0 0", "cpu 20 0 20 140 0 0 0 0"])
    monkeypatch.setattr(Path, "read_text", lambda _: next(samples))
    reader = OsResourceReader()
    assert reader._cpu()["percent"] is None
    assert reader._cpu() == {"percent": 50}
    assert reader._cpu() == {"percent": 0}
    monkeypatch.setattr(Path, "read_text", lambda _: "MemTotal: 1000 kB\nMemAvailable: 250 kB\n")
    assert OsResourceReader._memory() == {"percent": 75, "used_bytes": 750 * 1024, "total_bytes": 1000 * 1024}


def test_gpu_sampling_supported_partial_and_unavailable(monkeypatch):
    import subprocess
    from rag.deployment.adapters import gpu_metrics

    def run(command, **kwargs):
        assert command[0] == "nvidia-smi"
        assert kwargs["timeout"] == 2 and kwargs["check"] is True
        return subprocess.CompletedProcess(command, 0, 'GPU-1, NVIDIA RTX, 0, 1024, 8192, 42, 18.5\nGPU-2, NVIDIA RTX, [Not Supported], N/A, 8192, N/A, N/A\n')
    monkeypatch.setattr(gpu_metrics.subprocess, "run", run)
    sample = gpu_metrics.read_gpu_metrics()
    assert sample.unavailable_reason is None
    assert sample.devices[0].utilization_percent == 0
    assert sample.devices[0].memory_used_bytes == 1024 ** 3
    assert sample.devices[1].utilization_percent is None
    assert sample.devices[1].memory_total_bytes == 8 * 1024 ** 3
    for error in (FileNotFoundError("private"), subprocess.TimeoutExpired("private", 2), subprocess.CalledProcessError(1, "private")):
        def fail(*args, **kwargs):
            raise error
        monkeypatch.setattr(gpu_metrics.subprocess, "run", fail)
        sample = gpu_metrics.read_gpu_metrics()
        assert sample.devices == [] and sample.unavailable_reason
        assert "private" not in sample.model_dump_json()
    for output in ('', 'bad,row', 'GPU-1, RTX, NaN, 0, 8192, 42, 1', 'GPU-1, RTX, 101, 0, 8192, 42, 1'):
        monkeypatch.setattr(gpu_metrics.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess([], 0, output))
        assert gpu_metrics.read_gpu_metrics().unavailable_reason
