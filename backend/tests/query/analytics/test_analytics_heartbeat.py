"""Heartbeat lifetime across the shared sync, streaming and artifact query paths."""

from datetime import UTC, datetime
from threading import Event, Thread
from types import SimpleNamespace

import pytest

from rag.auth.context import UserContext
from rag.query.analytics.adapters.memory import InMemoryAnalyticsRepository
from rag.query.analytics.service import AnalyticsRecorder
from rag.query.cancellation import QueryCancelled
from rag.query.schemas import QueryRequest, QueryStreamEvent, RAGResponse
from rag.query.service import LocalRagService


@pytest.mark.parametrize('path', ['sync', 'stream', 'tracker', 'artifact', 'artifact_stream', 'cancel', 'error', 'close'])
def test_query_heartbeats_span_blocking_work_and_stop_on_every_exit(monkeypatch, path):
    repository = InMemoryAnalyticsRepository()
    recorder = AnalyticsRecorder(repository, reconciliation_grace_seconds=1)
    beat_seen = Event()
    threads = []
    real_heartbeat = repository.heartbeat_execution

    def heartbeat(execution_id, **kwargs):
        updated = real_heartbeat(execution_id, **kwargs)
        beat_seen.set()
        return updated

    def thread(**kwargs):
        instance = Thread(**kwargs)
        threads.append(instance)
        return instance

    monkeypatch.setattr(repository, 'heartbeat_execution', heartbeat)
    monkeypatch.setattr('rag.query.analytics.heartbeat.Thread', thread)
    service = LocalRagService.__new__(LocalRagService)
    service.rag_config = SimpleNamespace(retrieval_token_budget=100)
    service.analytics_recorder = recorder
    service.analytics_cohort = {}
    service.nodes = object()
    service._async_artifact_request = lambda request: object() if path.startswith('artifact') else None
    service._record_completed_query = lambda **kwargs: None

    def response(ctx):
        assert beat_seen.wait(2), 'heartbeat did not run during blocking work'
        if path == 'cancel':
            raise QueryCancelled()
        if path == 'error':
            raise RuntimeError('provider failed')
        return RAGResponse(trace_id=ctx['trace_id'], session_id=ctx['session_id'], answer='Answer',
                           conflict_flag=False, faithfulness_score=1, intent='factual_simple', latency_ms=1, degraded=False)

    service.graph = SimpleNamespace(invoke=lambda ctx: {**ctx, 'response': response(ctx)})
    service._handle_artifact_request = lambda **ctx: response(ctx)

    def stream(ctx, nodes):
        answer = response(ctx)
        yield QueryStreamEvent(event='trace', data={'trace_id': ctx['trace_id']})
        yield QueryStreamEvent(event='done', data=answer.model_dump())

    monkeypatch.setattr('rag.query.service.stream_graph', stream)
    request = QueryRequest(query='A question')
    user = UserContext(user_id='test', email='test@example.test')
    if path in {'stream', 'tracker', 'artifact_stream', 'close'}:
        iterator = service.stream_query(request, user, analytics_origin='query_tracker' if path == 'tracker' else 'chat')
        if path == 'close':
            next(iterator)
            iterator.close()
        else:
            list(iterator)
    elif path in {'cancel', 'error'}:
        with pytest.raises(QueryCancelled if path == 'cancel' else RuntimeError):
            service.execute_query(request, user)
    else:
        service.execute_query(request, user)

    assert len(threads) == 1 and not threads[0].is_alive()
    record, = repository._records.values()
    assert record.last_heartbeat_at >= record.started_at
    assert record.lifecycle == 'terminal'
    assert record.outcome == {'close': 'interrupted', 'cancel': 'cancelled', 'error': 'system_error'}.get(path, 'complete')
    assert record.reason_code != 'analytics_heartbeat_expired'


def test_heartbeat_storage_failure_retries_without_changing_query_behavior(monkeypatch, caplog):
    calls = []
    recovered = Event()

    class Repository:
        def heartbeat_execution(self, execution_id, **kwargs):
            calls.append(execution_id)
            if len(calls) == 1:
                raise RuntimeError('sensitive connection details')
            recovered.set()
            return True

    recorder = AnalyticsRecorder(Repository(), reconciliation_grace_seconds=1)
    with recorder.heartbeat('execution'):
        assert recovered.wait(2)
    assert len(calls) == 2
    assert 'heartbeat failed' in caplog.text
    assert 'sensitive' not in caplog.text


def test_recorder_starts_a_new_heartbeat_window_even_for_a_backdated_request():
    repository = InMemoryAnalyticsRepository()
    recorder = AnalyticsRecorder(repository)
    now = datetime.now(UTC)
    recorder.start(execution_id='e', trace_id='t', session_id='s',
                   user=UserContext(user_id='u', email='u@example.test'), request=QueryRequest(query='Question'),
                   started_at=datetime(2020, 1, 1, tzinfo=UTC), origin='chat', work_kind='answer')
    row = repository.get_execution('e')
    assert row.last_heartbeat_at >= now
    assert row.reconciliation_deadline_at > row.last_heartbeat_at
