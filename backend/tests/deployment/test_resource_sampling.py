"""Dashboard requests stay independent of slow or failing resource collection."""

import asyncio
from datetime import UTC, datetime, timedelta
from queue import Queue
from types import SimpleNamespace

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from rag.auth.dependencies import require_platform_admin_user
from rag.deployment import resource_sampling
from rag.deployment.resource_metrics import ResourceSnapshot
from rag.deployment.resource_sampling import ResourceSampler
from rag.deployment.routes import router


def test_shared_sampling_nonblocking_requests_staleness_and_recovery(monkeypatch, caplog):
    clock = [100.0]
    monkeypatch.setattr(resource_sampling, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    entered: Queue[int] = Queue()
    results: Queue[ResourceSnapshot | Exception] = Queue()

    class SlowReader:
        calls = 0

        def read(self):
            self.calls += 1
            entered.put(self.calls)
            result = results.get(timeout=3)
            if isinstance(result, Exception):
                raise result
            return result

    async def admin():
        return object()

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_platform_admin_user] = admin
    reader = SlowReader()
    sampler = ResourceSampler(reader, interval_seconds=0.01)
    app.state.resource_sampler = sampler

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    async def burst(expected_status, expected_sample=None):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            responses = await asyncio.wait_for(asyncio.gather(*(
                client.get("/api/v1/admin/system-resources") for _ in range(50)
            ), client.get("/ping")), timeout=1)
        assert responses[-1].json() == {"ok": True}
        for response in responses[:-1]:
            assert response.status_code == expected_status
            assert response.headers["Cache-Control"] == "no-store"
            if expected_sample is not None:
                assert response.json() == expected_sample.model_dump(mode="json")
            else:
                assert response.headers["Retry-After"] == "2"

    first = ResourceSnapshot(sampled_at=datetime.now(UTC), metrics=[])
    sampler.start()
    try:
        assert entered.get(timeout=1) == 1
        asyncio.run(burst(503))  # Cold start never waits for the blocked collector.
        assert reader.calls == 1
        results.put(first)
        assert entered.get(timeout=1) == 2
        asyncio.run(burst(200, first))
        assert reader.calls == 2  # Fifty viewers share the same completed sample.
        results.put(OSError("private device details"))
        assert entered.get(timeout=1) == 3
        assert sampler.read() is first
        clock[0] += 11
        asyncio.run(burst(503))  # A failure must not freshen an old sample.
        assert "Resource sampling failed" in caplog.text
        assert "private device details" not in caplog.text
        results.put(first)  # Slow collection started before expiry is still stale.
        assert entered.get(timeout=1) == 4
        asyncio.run(burst(503))
        recovered = ResourceSnapshot(sampled_at=first.sampled_at + timedelta(seconds=11), metrics=[])
        results.put(recovered)
        assert entered.get(timeout=1) == 5
        asyncio.run(burst(200, recovered))
    finally:
        results.put(first)
        sampler.stop()
    assert not sampler._thread.is_alive()
