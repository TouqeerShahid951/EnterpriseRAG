from contextlib import contextmanager
from types import SimpleNamespace

from apps.background import artifact_cleanup
from rag.artifact_jobs.cleanup import GeneratedArtifactCleanupResult


def _empty_result() -> GeneratedArtifactCleanupResult:
    return GeneratedArtifactCleanupResult(
        scanned_count=0,
        deleted_count=0,
        missing_object_count=0,
        skipped_count=0,
    )


def test_non_postgres_cleanup_runs_one_bounded_feature_batch(monkeypatch) -> None:
    result = _empty_result()
    limits: list[int] = []
    service = SimpleNamespace(
        cleanup_expired=lambda *, limit: limits.append(limit) or result
    )
    monkeypatch.setattr(
        artifact_cleanup,
        "settings",
        SimpleNamespace(document_repository="memory"),
    )
    monkeypatch.setattr(
        artifact_cleanup,
        "get_generated_artifact_cleanup_service",
        lambda: service,
    )

    assert artifact_cleanup._run_with_lock() == result
    assert limits == [artifact_cleanup.DEFAULT_CLEANUP_BATCH_SIZE]


def test_postgres_cleanup_skips_when_advisory_lock_is_owned_elsewhere(
    monkeypatch,
) -> None:
    connection = _FakeConnection(acquired=False)
    monkeypatch.setattr(
        artifact_cleanup,
        "settings",
        SimpleNamespace(document_repository="postgres", database_url="postgresql://db"),
    )
    monkeypatch.setattr(
        artifact_cleanup,
        "_LockConnection",
        lambda _database_url: _FakeLock(connection),
    )
    monkeypatch.setattr(
        artifact_cleanup,
        "get_generated_artifact_cleanup_service",
        lambda: (_ for _ in ()).throw(AssertionError("cleanup must not run")),
    )

    assert artifact_cleanup._run_with_lock() is None
    assert connection.queries == ["SELECT pg_try_advisory_lock(%s) AS acquired"]


def test_postgres_cleanup_releases_advisory_lock_after_the_batch(monkeypatch) -> None:
    result = _empty_result()
    connection = _FakeConnection(acquired=True)
    monkeypatch.setattr(
        artifact_cleanup,
        "settings",
        SimpleNamespace(document_repository="postgres", database_url="postgresql://db"),
    )
    monkeypatch.setattr(
        artifact_cleanup,
        "_LockConnection",
        lambda _database_url: _FakeLock(connection),
    )
    monkeypatch.setattr(
        artifact_cleanup,
        "get_generated_artifact_cleanup_service",
        lambda: SimpleNamespace(cleanup_expired=lambda *, limit: result),
    )

    assert artifact_cleanup._run_with_lock() == result
    assert connection.queries == [
        "SELECT pg_try_advisory_lock(%s) AS acquired",
        "SELECT pg_advisory_unlock(%s)",
    ]


class _FakeResult:
    def __init__(self, acquired: bool) -> None:
        self._acquired = acquired

    def fetchone(self) -> dict[str, bool]:
        return {"acquired": self._acquired}


class _FakeConnection:
    def __init__(self, *, acquired: bool) -> None:
        self.acquired = acquired
        self.queries: list[str] = []

    def execute(self, query: str, _params: tuple[int]) -> _FakeResult:
        self.queries.append(query)
        return _FakeResult(self.acquired)


class _FakeLock:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    @contextmanager
    def _connect(self):
        yield self.connection
