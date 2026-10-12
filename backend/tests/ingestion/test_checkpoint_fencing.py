"""Fencing and HTTP error classification at the actual registry boundary."""
from contextlib import nullcontext
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

from rag.ingestion.adapters.backend import BackendInternalClient
from rag.ingestion.adapters.http import ServiceRequestError
from rag.ingestion.checkpoints.adapters.postgres import PostgresCheckpointRepository
from rag.ingestion.checkpoints.models import CheckpointDescriptor, CheckpointLeaseLost


def descriptor():
    return CheckpointDescriptor('job', 'doc', 'prepared', 'ingest-checkpoints/doc/job/prepared.gz', 2, '0'*64, 10, 20, '1'*64, '2'*64)


class Connection:
    def __init__(self):
        self.job = dict(document_id='doc', status='processing', run_token='live', deleted_at=None)
        self.row = asdict(descriptor())

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def transaction(self):
        return nullcontext()

    def execute(self, sql, params):
        if 'FROM ingest_jobs' in sql:
            return SimpleNamespace(fetchone=lambda: self.job)
        if sql.startswith('DELETE'):
            self.row = None
        return SimpleNamespace(fetchone=lambda: self.row)


def test_invalidation_requires_current_lease_and_exact_observed_reference():
    conn = Connection()
    repo = PostgresCheckpointRepository('unused')
    repo._connect = lambda: conn
    original = descriptor()
    with pytest.raises(CheckpointLeaseLost):
        repo.invalidate(original, run_token='stale')
    assert conn.row == asdict(original)
    assert not repo.invalidate(replace(original, body_sha256='3'*64), run_token='live')
    assert conn.row == asdict(original)
    assert repo.commit(original, run_token='live') == original
    with pytest.raises(ValueError, match='different content'):
        repo.commit(replace(original, body_sha256='3'*64), run_token='live')
    assert repo.invalidate(original, run_token='live')
    assert conn.row is None
    assert repo.invalidate(original, run_token='live')


@pytest.mark.parametrize('mutation', [{'deleted_at': 'now'}, {'status': 'cancelled'}, {'status': 'complete'}])
def test_terminal_or_deleted_jobs_cannot_invalidate(mutation):
    conn = Connection()
    conn.job.update(mutation)
    repo = PostgresCheckpointRepository('unused')
    repo._connect = lambda: conn
    with pytest.raises(CheckpointLeaseLost):
        repo.invalidate(descriptor(), run_token='live')
    assert conn.row is not None


@pytest.mark.parametrize('operation', ['commit_checkpoint', 'invalidate_checkpoint'])
def test_checkpoint_conflict_does_not_discard_the_live_lease(monkeypatch, operation):
    from rag.ingestion.adapters import backend as module
    client = BackendInternalClient(base_url='unused', service_token='test', timeout_seconds=1)
    client._bind_run_token('job', 'live')
    def conflict(*args, **kwargs):
        raise ServiceRequestError('backend', '{"detail":{"code":"checkpoint_conflict"}}', 409)
    monkeypatch.setattr(module, 'request_json', conflict)
    with pytest.raises(ServiceRequestError):
        getattr(client, operation)(descriptor())
    client.ensure_lease('job')
    assert client._require_run_token('job') == 'live'


def test_invalidation_http_requires_service_token_and_distinguishes_lease_loss(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from rag.core.config import settings
    from rag.ingestion.checkpoints.dependencies import get_checkpoint_service
    from rag.ingestion.checkpoints.routes import router
    from rag.ingestion.checkpoints.service import CheckpointService
    connection = Connection()
    repo = PostgresCheckpointRepository('unused')
    repo._connect = lambda: connection
    app = FastAPI()
    app.include_router(router, prefix='/internal')
    app.dependency_overrides[get_checkpoint_service] = lambda: CheckpointService(repo, None)
    monkeypatch.setattr(settings, 'service_token', 'test-token')
    body = asdict(descriptor())
    body.pop('job_id')
    body['run_token'] = 'live'
    with TestClient(app) as client:
        path = '/internal/ingest/jobs/job/checkpoints'
        assert client.request('DELETE', path, json=body).status_code == 401
        headers = {'X-Service-Token': 'test-token'}
        stale = client.request('DELETE', path, json=body | {'run_token': 'stale'}, headers=headers)
        assert stale.status_code == 409
        assert stale.json()['detail']['code'] == 'ingest_job_lease_lost'
        conflict = client.post(path, json=body | {'body_sha256': '3'*64}, headers=headers)
        assert conflict.status_code == 409
        assert conflict.json()['detail']['code'] == 'checkpoint_conflict'
        assert connection.row == asdict(descriptor())
        removed = client.request('DELETE', path, json=body, headers=headers)
        assert removed.status_code == 200
        assert removed.json() == {'invalidated': True}
        assert connection.row is None
