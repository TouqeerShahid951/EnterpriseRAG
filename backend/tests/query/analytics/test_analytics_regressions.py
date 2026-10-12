"""Analytics contract regressions, exercised against memory and disposable PostgreSQL."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import os
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rag.auth.dependencies import require_platform_admin_user
from rag.query.analytics.adapters.memory import InMemoryAnalyticsRepository
from rag.query.analytics.adapters.postgres import PostgresAnalyticsRepository
from rag.query.analytics.models import AnalyticsExecutionRecord, AnalyticsFilters
from rag.query.analytics.repository import get_analytics_repository
from rag.query.analytics.routes import router
from rag.query.analytics.schema import ANALYTICS_SCHEMA_SQL
from rag.query.analytics.schemas import execution_response
from rag.query.analytics.service import _retrieval_lineage
from rag.query.qdrant import SearchHit
from rag.query.retrieval.retrieval_trace import retrieval_trace_stage

ACTOR = '00000000-0000-0000-0000-000000000001'


@pytest.fixture(params=['memory', 'postgres'])
def repository(request):
    if request.param == 'memory':
        yield InMemoryAnalyticsRepository()
        return
    database_url = os.getenv('TEST_DATABASE_URL')
    if not database_url:
        pytest.skip('TEST_DATABASE_URL is required for disposable PostgreSQL analytics tests')
    import psycopg
    from psycopg.conninfo import make_conninfo
    from psycopg import sql
    from rag.shared.persistence import close_postgres_pools

    schema = 'analytics_test_' + uuid4().hex
    with psycopg.connect(database_url, autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        connection_url = make_conninfo(database_url, options=f'-csearch_path={schema}')
        try:
            with psycopg.connect(connection_url) as conn:
                conn.execute('CREATE TABLE users (id UUID PRIMARY KEY)')
                conn.execute('INSERT INTO users VALUES (%s)', (ACTOR,))
                conn.execute(ANALYTICS_SCHEMA_SQL)
                conn.execute(ANALYTICS_SCHEMA_SQL)
            yield PostgresAnalyticsRepository(connection_url)
        finally:
            close_postgres_pools()
            admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


def store(repository, *, started=None, lineage=None, outcome='complete', origin='chat', work_kind='answer', finished=None, deadline=None, heartbeat=None):
    started = started or datetime.now(UTC) - timedelta(minutes=1)
    record = AnalyticsExecutionRecord(
        execution_id=str(uuid4()), trace_id=str(uuid4()), session_id=str(uuid4()),
        actor_id=ACTOR, permission_version=1, origin=origin, work_kind=work_kind,
        group_path='/ops', lifecycle='in_flight', started_at=started,
        requested_source_mode='corpus_only', reconciliation_deadline_at=deadline,
        last_heartbeat_at=heartbeat,
    )
    repository.start_execution(record)
    if outcome is not None:
        repository.finish_execution(
            record.execution_id, finished_at=finished or started + timedelta(seconds=1), outcome=outcome,
            retrieval_lineage_status='available' if lineage else 'not_captured', retrieval_lineage=lineage,
        )
    return repository.get_execution(record.execution_id)


def window():
    now = datetime.now(UTC)
    return AnalyticsFilters(created_from=now-timedelta(days=30), created_to=now)


def test_requested_mode_survives_storage_retry_and_terminal_failure(repository):
    row = store(repository, outcome=None)
    assert row.requested_source_mode == 'corpus_only'
    repository.start_execution(replace(row, requested_source_mode='db_only'))
    repository.finish_execution(row.execution_id, finished_at=datetime.now(UTC), outcome='system_error')
    repository.finish_execution(row.execution_id, finished_at=datetime.now(UTC), outcome='cancelled')
    saved = repository.get_execution(row.execution_id)
    assert saved.requested_source_mode == 'corpus_only'
    assert saved.outcome == 'system_error'


def test_stage_percentiles_sum_retries_per_execution(repository):
    store(repository, lineage={'performance': {'node_timings': [
        {'node': 'retrieve', 'duration_ms': 100}, {'node': 'retrieve', 'duration_ms': 200},
    ]}})
    store(repository, lineage={'performance': {'node_timings': [{'node': 'retrieve', 'duration_ms': 500}]}})
    timing, = repository.diagnose_executions(filters=window()).timings
    assert timing.execution_count == 2
    assert timing.duration_count == 3
    assert timing.p50_ms == 400
    assert timing.p95_ms == 490


def test_reconciliation_preserves_terminal_and_locked_records(repository):
    now = datetime.now(UTC)
    completed = store(repository, deadline=now-timedelta(seconds=1))
    due = store(repository, outcome=None, deadline=now-timedelta(seconds=1), heartbeat=now-timedelta(minutes=1))
    args = dict(as_of=now, retention_before=now-timedelta(days=30), batch_size=10)
    assert repository.maintain(**args, reconcile=False).reconciled_execution_count == 0
    assert repository.get_execution(due.execution_id).lifecycle == 'in_flight'
    if isinstance(repository, PostgresAnalyticsRepository):
        import psycopg
        with psycopg.connect(repository.database_url) as conn:
            conn.execute('SELECT execution_id FROM query_analytics_executions WHERE execution_id = %s FOR UPDATE', (due.execution_id,))
            assert repository.maintain(**args).reconciled_execution_count == 0
    assert repository.maintain(**args).reconciled_execution_count == 1
    assert repository.maintain(**args).reconciled_execution_count == 0
    assert repository.get_execution(due.execution_id).outcome == 'interrupted'
    assert repository.get_execution(completed.execution_id).outcome == 'complete'


def test_heartbeat_protects_long_queries_and_recovers_after_an_outage(repository):
    now = datetime.now(UTC)
    args = dict(as_of=now, retention_before=now-timedelta(days=30), batch_size=10)
    old_query = store(repository, outcome=None, started=now-timedelta(days=31),
                      heartbeat=now-timedelta(hours=2), deadline=now-timedelta(hours=1))
    legacy = store(repository, outcome=None, started=now-timedelta(days=31), deadline=now-timedelta(hours=1))
    assert repository.heartbeat_execution(old_query.execution_id, grace_seconds=60)
    active = repository.get_execution(old_query.execution_id)
    assert active.last_heartbeat_at > old_query.last_heartbeat_at
    assert active.reconciliation_deadline_at > now
    assert repository.maintain(**args).reconciled_execution_count == 0
    assert execution_response(active).liveness_status == 'active'
    assert execution_response(legacy).liveness_status == 'untracked'

    later = active.reconciliation_deadline_at+timedelta(seconds=1)
    result = repository.maintain(**{**args, 'as_of': later})
    assert result.reconciled_execution_count == 1
    assert result.deleted_execution_count == 0
    inferred = repository.get_execution(old_query.execution_id)
    assert inferred.outcome == 'interrupted'
    assert inferred.reason_code == 'analytics_heartbeat_expired'
    assert execution_response(inferred).liveness_status == 'heartbeat_expired'
    assert repository.get_execution(legacy.execution_id).lifecycle == 'in_flight'
    assert not repository.heartbeat_execution(legacy.execution_id, grace_seconds=60)
    assert repository.heartbeat_execution(old_query.execution_id, grace_seconds=60)
    restored = repository.get_execution(old_query.execution_id)
    assert (restored.lifecycle, restored.outcome, restored.finished_at, restored.reason_code) == ('in_flight', None, None, None)


def test_actual_completion_corrects_only_inferred_interruption(repository):
    now = datetime.now(UTC)
    query = store(repository, outcome=None, heartbeat=now-timedelta(minutes=2), deadline=now-timedelta(minutes=1))
    repository.maintain(as_of=now, retention_before=now-timedelta(days=30), batch_size=10)
    saved = repository.finish_execution(query.execution_id, outcome='complete', finished_at=now, latency_ms=300, degraded=False)
    assert saved.outcome == 'complete'
    assert saved.reason_code is saved.degraded_reason is None
    assert saved.degraded is False
    assert execution_response(saved).liveness_status == 'finished'
    assert not repository.heartbeat_execution(query.execution_id, grace_seconds=60)
    repository.finish_execution(query.execution_id, outcome='cancelled', finished_at=now)
    assert repository.get_execution(query.execution_id).outcome == 'complete'

    cancelled = store(repository, outcome='cancelled', heartbeat=now, deadline=now+timedelta(minutes=1))
    assert not repository.heartbeat_execution(cancelled.execution_id, grace_seconds=60)
    repository.finish_execution(cancelled.execution_id, outcome='complete', finished_at=now)
    assert repository.get_execution(cancelled.execution_id).outcome == 'cancelled'

    with pytest.raises(ValueError):
        repository.heartbeat_execution(query.execution_id, grace_seconds=0)


def test_killed_query_process_is_reconciled_after_its_last_heartbeat(repository):
    if not isinstance(repository, PostgresAnalyticsRepository):
        pytest.skip('process-crash recovery requires shared PostgreSQL storage')
    import json
    import select
    import subprocess
    import sys

    execution_id = str(uuid4())
    code = '''
import json, sys
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import uuid4
from rag.query.analytics.adapters.postgres import PostgresAnalyticsRepository
from rag.query.analytics.models import AnalyticsExecutionRecord
from rag.query.analytics.heartbeat import execution_heartbeat
args = json.loads(sys.stdin.readline())
repo = PostgresAnalyticsRepository(args['database_url'])
now = datetime.now(UTC)
repo.start_execution(AnalyticsExecutionRecord(
    execution_id=args['execution_id'], trace_id=str(uuid4()), session_id=str(uuid4()),
    actor_id=args['actor_id'], permission_version=1, origin='chat', work_kind='answer',
    group_path='/ops', lifecycle='in_flight', started_at=now,
    last_heartbeat_at=now, reconciliation_deadline_at=now+timedelta(seconds=1)))
renew = repo.heartbeat_execution
def beat(*args, **kwargs):
    result = renew(*args, **kwargs)
    print('heartbeat', flush=True)
    return result
repo.heartbeat_execution = beat
with execution_heartbeat(repo, args['execution_id'], grace_seconds=1):
    Event().wait()
'''
    process = subprocess.Popen([sys.executable, '-c', code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        process.stdin.write(json.dumps({'database_url': repository.database_url, 'execution_id': execution_id, 'actor_id': ACTOR})+'\n')
        process.stdin.close()
        assert select.select([process.stdout], [], [], 10)[0], 'child heartbeat did not arrive'
        assert process.stdout.readline().strip() == 'heartbeat'
        process.kill()
        process.wait(timeout=5)
        row = repository.get_execution(execution_id)
        assert row.last_heartbeat_at > row.started_at
        assert repository.maintain(as_of=row.last_heartbeat_at, retention_before=row.started_at-timedelta(days=30), batch_size=1).reconciled_execution_count == 0
        # Advance the maintenance clock past the persisted deadline after SIGKILL.
        result = repository.maintain(as_of=row.reconciliation_deadline_at+timedelta(seconds=1),
                                     retention_before=row.started_at-timedelta(days=30), batch_size=1)
        assert result.reconciled_execution_count == 1
        assert repository.get_execution(execution_id).reason_code == 'analytics_heartbeat_expired'
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        process.stdout.close()


def test_lineage_expires_in_bounded_batches_without_removing_timings_or_live_queries(repository):
    now = datetime.now(UTC)
    lineage = {'stages': [{'name': 'retrieved', 'candidates': [{'doc_id': 'private'}]}],
               'performance': {'node_timings': [{'node': 'retrieve', 'duration_ms': 300}]}}
    expired = [store(repository, started=now-timedelta(days=8), lineage=lineage) for _ in range(2)]
    recent = store(repository, started=now-timedelta(days=20), finished=now-timedelta(days=1), lineage=lineage)
    active = store(repository, started=now-timedelta(days=31), outcome=None)
    doomed = store(repository, started=now-timedelta(days=31))
    args = dict(as_of=now, retention_before=now-timedelta(days=30), lineage_before=now-timedelta(days=7), batch_size=1)
    assert repository.maintain(**args).expired_lineage_count == 1
    assert repository.maintain(**args).expired_lineage_count == 1
    assert repository.maintain(**args).expired_lineage_count == 0
    for record in expired:
        saved = repository.get_execution(record.execution_id)
        assert saved.retrieval_lineage_status == 'expired'
        assert 'stages' not in saved.retrieval_lineage
        assert saved.retrieval_lineage['performance'] == lineage['performance']
    assert repository.get_execution(recent.execution_id).retrieval_lineage_status == 'available'
    assert repository.get_execution(active.execution_id).lifecycle == 'in_flight'
    assert repository.get_execution(doomed.execution_id) is None


def test_default_http_population_and_explicit_all_origins(repository):
    store(repository)
    store(repository, origin='evaluation', outcome='system_error')
    store(repository, work_kind='artifact_submission', outcome='artifact_submitted')
    with client_for(repository) as client:
        summary = client.get('/api/v1/admin/query-analytics/summary').json()
        executions = client.get('/api/v1/admin/query-analytics/executions').json()
        all_summary = client.get('/api/v1/admin/query-analytics/summary', params={'origin':'all','work_kind':'all'}).json()
        assert summary['total_executions'] == 1
        assert executions['total'] == 1
        assert all_summary['total_executions'] == 3


def test_historical_titles_are_redacted_from_detail_and_aggregate(repository):
    lineage = {'stages': [{'name':'retrieved','attempt':0,'status':'completed','candidate_count':1,'truncated':False,
                          'candidates':[{'candidate_key':'g:d:c:p','index_generation_id':'g','doc_id':'d','chunk_id':'c',
                                         'point_id':'p','rank':1,'retrieval_score':0.9,'doc_title':'Private old title',
                                         'evidence_text':'Private old evidence','unknown_future_field':'Private text'}]}]}
    record = store(repository, lineage=lineage)
    with client_for(repository) as client:
        detail = client.get('/api/v1/admin/query-analytics/executions/'+record.execution_id)
        diagnostics = client.get('/api/v1/admin/query-analytics/diagnostics')
        assert detail.status_code == diagnostics.status_code == 200
        assert 'Private' not in detail.text
        assert 'Private' not in diagnostics.text
        assert diagnostics.json()['documents']['top_documents'][0]['document_title'] is None
    assert 'doc_id' in execution_response(record).retrieval_lineage['stages'][0]['candidates'][0]


def test_capture_uses_candidate_allowlist():
    stage = retrieval_trace_stage('retrieved', [SearchHit(point_id='p',score=0.8,payload={
        'doc_id':'d','chunk_id':'c','text':'Private evidence','doc_title':'Private title',
        '_rerank_error':'Private error','structured_origin':'Private origin',
    })], attempt=0)
    _, lineage = _retrieval_lineage({'retrieval_trace':[stage]}, response=None, max_candidates=500, max_bytes=512000)
    import json
    assert 'Private' not in json.dumps(lineage)
    assert lineage['stages'][0]['candidates'][0]['doc_id'] == 'd'


def test_list_snapshot_excludes_late_insertions_and_detail_is_independent(repository):
    first = store(repository)
    with client_for(repository) as client:
        first_page = client.get('/api/v1/admin/query-analytics/executions', params={'limit':1}).json()
        late = store(repository, started=first.started_at+timedelta(seconds=1))
        second_page = client.get('/api/v1/admin/query-analytics/executions', params={
            'from': first_page['created_from'], 'to': first_page['created_to'],
            'as_of': first_page['as_of'], 'limit':1,'offset':1,
        }).json()
        assert second_page['total'] == 1
        assert second_page['items'] == []
        assert client.get('/api/v1/admin/query-analytics/executions/'+late.execution_id).status_code == 200
        assert client.get('/api/v1/admin/query-analytics/executions/'+str(uuid4())).status_code == 404


def client_for(repository):
    app = FastAPI()
    app.include_router(router, prefix='/api/v1')
    app.dependency_overrides[get_analytics_repository] = lambda: repository
    app.dependency_overrides[require_platform_admin_user] = lambda: object()
    return TestClient(app)
