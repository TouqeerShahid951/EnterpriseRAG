from rag.shared import persistence


class _FakePool:
    def __init__(self) -> None:
        self.closed = False
        self.connection_count = 0

    def connection(self) -> object:
        self.connection_count += 1
        return object()

    def close(self) -> None:
        self.closed = True


def test_postgres_connections_reuse_one_pool_per_process(monkeypatch) -> None:
    persistence.close_postgres_pools()
    pools: list[_FakePool] = []

    def create_pool(_database_url: str) -> _FakePool:
        pool = _FakePool()
        pools.append(pool)
        return pool

    monkeypatch.setattr(persistence, "_create_postgres_pool", create_pool)
    repository = persistence.PostgresConnectionMixin()
    repository.database_url = "postgresql://example"

    repository._connect()
    repository._connect()

    assert len(pools) == 1
    assert pools[0].connection_count == 2

    persistence.close_postgres_pools()
    assert pools[0].closed is True
