"""Recovery regressions through the worker client and real stage serializers."""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from minio.error import S3Error
from urllib3.exceptions import MaxRetryError

from rag.ingestion.adapters.http import ServiceRequestError
from rag.ingestion.checkpoints.adapters.storage import CheckpointObjectStorage
from rag.ingestion.checkpoints.service import encode_payload
from rag.ingestion.checkpoints.worker import WorkerCheckpointClient
from rag.ingestion.chunking.chunker import TextChunk
from rag.ingestion.config import MinioConfig
from rag.ingestion.contracts import IngestJobPayload
from rag.ingestion.pipeline.indexing_stages import (
    _configuration_digest, _resume_dense_vectors, _save_prepared_checkpoint,
    _sparse_batch_from_payload,
)
from rag.ingestion.pipeline.resume import restore_prepared_state
from rag.ingestion.pipeline.state import IngestDependencies
from rag.shared.contracts.abbreviations import ABBREVIATION_GLOSSARY_DOC_TYPE


class Registry:
    def __init__(self):
        self.values = {}
        self.progress = []

    def commit_checkpoint(self, descriptor):
        key = (descriptor.job_id, descriptor.stage_key)
        if key in self.values and self.values[key] != descriptor:
            raise ValueError('checkpoint already exists with different content')
        self.values[key] = descriptor
        return descriptor

    def get_checkpoint(self, *, job_id, stage_key):
        return self.values.get((job_id, stage_key))

    def invalidate_checkpoint(self, descriptor):
        key = (descriptor.job_id, descriptor.stage_key)
        if self.values.get(key) != descriptor:
            return False
        del self.values[key]
        return True

    def list_checkpoints(self, *, job_id, stage_prefix):
        return tuple(d for (j, s), d in self.values.items() if j == job_id and s.startswith(stage_prefix))

    def get_job_status(self, *, job_id):
        return SimpleNamespace(doc_id='doc', status='failed', retry_of_job_id=None)

    def update_job(self, **kwargs):
        self.progress.append(kwargs)


class Objects:
    def __init__(self):
        self.values = {}

    def put(self, *, object_key, content):
        self.values[object_key] = content

    def read(self, *, object_key):
        if object_key not in self.values:
            raise FileNotFoundError(object_key)
        return self.values[object_key]


class Model:
    chat_model = 'chat'
    embed_model = 'embed'

    def __init__(self):
        self.inputs = []
        self.fail_at = None

    def embed_many(self, texts, *, progress=None):
        self.inputs.append(list(texts))
        if texts[0] == self.fail_at:
            raise RuntimeError('simulated worker failure')
        return [[float(text), 1.0] for text in texts]


def context(registry=None, objects=None, *, count=40):
    registry = registry or Registry()
    objects = objects or Objects()
    deps = IngestDependencies(
        backend=registry, storage=None, image_asset_writer=None, ollama=Model(),
        vision=SimpleNamespace(model='vision-a'), sparse_embedder=SimpleNamespace(model_name='sparse'),
        qdrant=None, min_chars_per_page=80, chunk_target_tokens=512,
        chunk_overlap_tokens=64, parent_max_tokens=1024,
        checkpoint=WorkerCheckpointClient(backend=registry, storage=objects),
    )
    job = IngestJobPayload('job', 'doc', 'doc.pdf', '/test', None, [])
    chunks = [TextChunk(index=i, page=1, text=str(i), parent_chunk_id='doc:parent:0',
                        parent_text=str(i), chunk_type='text', section_title=None,
                        page_start=1, page_end=1) for i in range(count)]
    state = dict(payload=job, file_bytes=b'source', chunks=chunks,
                 embedding_texts=[str(i) for i in range(count)], claims=[], metadata={})
    return state, deps


@pytest.mark.parametrize('damage', ['configuration', 'missing', 'corrupt'])
def test_unusable_checkpoint_can_be_recomputed(damage):
    state, deps = context(count=1)
    _save_prepared_checkpoint(state, deps)
    descriptor = deps.backend.get_checkpoint(job_id='job', stage_key='prepared')
    if damage == 'configuration':
        deps = replace(deps, chunk_target_tokens=256)
    elif damage == 'missing':
        del deps.checkpoint.storage.values[descriptor.object_key]
    else:
        deps.checkpoint.storage.values[descriptor.object_key] = b'corrupt'
    assert not restore_prepared_state(dict(payload=state['payload'], file_bytes=b'source'), deps, _configuration_digest(deps))
    _save_prepared_checkpoint(state, deps)
    assert restore_prepared_state(dict(payload=state['payload'], file_bytes=b'source'), deps, _configuration_digest(deps))


def test_gzip_serialization_is_independent_of_wall_clock():
    # Python 3.12 uses time when mtime is omitted; exercise that behavior on any host Python.
    import gzip
    original = gzip.compress
    with patch('rag.ingestion.checkpoints.service.gzip.compress', side_effect=lambda data, **kw: original(data, **({'mtime': 100} | kw))):
        first = encode_payload({'value': 'same'})
    with patch('rag.ingestion.checkpoints.service.gzip.compress', side_effect=lambda data, **kw: original(data, **({'mtime': 101} | kw))):
        second = encode_payload({'value': 'same'})
    assert first == second


@pytest.mark.parametrize('field,value', [('vision_layout_repair_enabled', True), ('ocr_review_confidence_threshold', .99), ('vision', SimpleNamespace(model='vision-b'))])
def test_parser_changes_invalidate_prepared_output(field, value):
    _, deps = context()
    assert _configuration_digest(deps) != _configuration_digest(replace(deps, **{field: value}))


def test_prepared_output_binds_document_options():
    state, deps = context(count=1)
    _save_prepared_checkpoint(state, deps)
    changed = replace(state['payload'], description='changed', analyze_slide_visuals=False)
    assert not restore_prepared_state(dict(payload=changed, file_bytes=b'source'), deps, _configuration_digest(deps))


def test_glossary_checkpoint_restores_without_embeddings():
    state, deps = context(count=1)
    state.update(payload=replace(state['payload'], doc_type=ABBREVIATION_GLOSSARY_DOC_TYPE), embedding_texts=[], abbreviation_entries=[{'abbreviation': 'AI', 'expansion': 'Artificial Intelligence'}])
    _save_prepared_checkpoint(state, deps)
    resumed = dict(payload=state['payload'], file_bytes=b'source')
    assert restore_prepared_state(resumed, deps, _configuration_digest(deps))
    assert resumed['abbreviation_entries'] == state['abbreviation_entries']
    assert resumed['embedding_texts'] == []


def test_dense_restart_preserves_saved_ranges_after_batch_size_change():
    state, deps = context()
    _save_prepared_checkpoint(state, deps)
    deps.ollama.fail_at = '16'
    with pytest.raises(RuntimeError, match='simulated'):
        _resume_dense_vectors(state, deps, state['embedding_texts'], lambda *_: None)
    _, restarted = context(deps.backend, deps.checkpoint.storage)
    restarted = replace(restarted, embedding_batch_size=8)
    resumed = dict(payload=state['payload'], file_bytes=b'source')
    assert restore_prepared_state(resumed, restarted, _configuration_digest(restarted))
    vectors = _resume_dense_vectors(resumed, restarted, resumed['embedding_texts'], lambda *_: None)
    assert restarted.ollama.inputs == [[str(i) for i in range(16,32)], [str(i) for i in range(32,40)]]
    assert vectors == [[float(i), 1.0] for i in range(40)]


@pytest.mark.parametrize('indices,values', [([-1],[1.0]), ([1.5],[1.0]), ([1,1],[1.0,2.0]), ([1],[float('nan')]), ([1],[float('inf')])])
def test_invalid_sparse_vectors_are_rejected(indices, values):
    assert _sparse_batch_from_payload([dict(indices=indices, values=values)], 1) is None


@pytest.mark.parametrize('operation', ['read', 'put'])
def test_storage_connection_failure_is_retryable(operation):
    storage = CheckpointObjectStorage(MinioConfig('unused', '', '', 'unused', False))
    class Unavailable:
        def get_object(self, *args):
            raise MaxRetryError(None, 'private-url', reason=ConnectionError('private-details'))
        def bucket_exists(self, *args):
            return self.get_object()
    storage._client = lambda: Unavailable()
    with pytest.raises(ServiceRequestError) as raised:
        getattr(storage, operation)(object_key='key', **({'content': b'bytes'} if operation == 'put' else {}))
    assert raised.value.status_code == 503
    assert 'private' not in str(raised.value)


def test_storage_missing_object_is_distinct_from_outage():
    storage = CheckpointObjectStorage(MinioConfig('unused', '', '', 'unused', False))
    class Missing:
        def get_object(self, *args):
            raise S3Error(response=None, code='NoSuchKey', message='missing', resource='resource', request_id='request', host_id='host')
    storage._client = lambda: Missing()
    with pytest.raises(FileNotFoundError):
        storage.read(object_key='key')


def test_linked_retry_does_not_reread_predecessor_after_local_copy():
    state, deps = context(count=1)
    _save_prepared_checkpoint(state, deps)
    deps.checkpoint.adopt_predecessor(job_id='next', document_id='doc', predecessor_job_id='job')
    source = deps.backend.get_checkpoint(job_id='job', stage_key='prepared')
    del deps.checkpoint.storage.values[source.object_key]
    assert deps.checkpoint.adopt_predecessor(job_id='next', document_id='doc', predecessor_job_id='job') == 0


def test_embedding_model_change_preserves_preparation_but_invalidates_vectors():
    state, deps = context(count=1)
    _save_prepared_checkpoint(state, deps)
    _resume_dense_vectors(state, deps, state['embedding_texts'], lambda *_: None)
    changed_model = Model()
    changed_model.embed_model = 'replacement'
    changed = replace(deps, ollama=changed_model)
    resumed = dict(payload=state['payload'], file_bytes=b'source')
    assert restore_prepared_state(resumed, changed, _configuration_digest(changed))
    assert _configuration_digest(deps, 'parsed') == _configuration_digest(changed, 'parsed')
    assert _resume_dense_vectors(resumed, changed, resumed['embedding_texts'], lambda *_: None) == [[0., 1.]]
    assert changed_model.inputs == [['0']]


def test_changed_approved_review_contents_invalidate_prepared():
    from rag.ingestion.pipeline.resume import refresh_review_context
    state, deps = context(count=1)
    state['payload'] = replace(state['payload'], review_batch_id='review')
    deps.backend.get_review_batch_parsed_items = lambda **_: [{'text': 'approved first'}]
    refresh_review_context(state, deps)
    _save_prepared_checkpoint(state, deps)
    resumed = dict(payload=state['payload'], file_bytes=b'source')
    deps.backend.get_review_batch_parsed_items = lambda **_: [{'text': 'approved correction'}]
    refresh_review_context(resumed, deps)
    assert not restore_prepared_state(resumed, deps, _configuration_digest(deps))


@pytest.mark.parametrize('damage', ['missing', 'corrupt'])
def test_middle_batch_recomputed_and_saved_progress_counts_only_valid_ranges(damage):
    state, deps = context()
    _save_prepared_checkpoint(state, deps)
    _resume_dense_vectors(state, deps, state['embedding_texts'], lambda *_: None)
    descriptor = deps.backend.get_checkpoint(job_id='job', stage_key='dense:16:32')
    if damage == 'missing':
        del deps.checkpoint.storage.values[descriptor.object_key]
    else:
        deps.checkpoint.storage.values[descriptor.object_key] = b'broken'
    deps.ollama.inputs.clear()
    deps.backend.progress.clear()
    vectors = _resume_dense_vectors(state, deps, state['embedding_texts'], lambda *_: None)
    assert vectors == [[float(i), 1.] for i in range(40)]
    assert deps.ollama.inputs == [[str(i) for i in range(16,32)]]
    saved = [item['stage_progress']['current'] for item in deps.backend.progress]
    assert saved == [16, 24, 40]


def test_storage_outage_uses_durable_job_retry(monkeypatch):
    from contextlib import nullcontext
    from rag.ingestion import execution
    state, _ = context(count=1)
    config = SimpleNamespace(heartbeat_interval_seconds=0)
    class Backend:
        failure = None
        def get_job_status(self, **kwargs):
            return SimpleNamespace(status="processing")
        def record_event(self, **kwargs):
            pass
        def record_failure(self, **kwargs):
            self.failure = kwargs
            return SimpleNamespace(retry_scheduled=True, failure_attempt_count=1, job_status='queued')
    backend = Backend()
    monkeypatch.setattr(execution.WorkerConfig, 'from_env', lambda: config)
    monkeypatch.setattr(execution, 'build_backend_client', lambda _: backend)
    monkeypatch.setattr(execution, '_start_attempt', lambda *_args, **_kwargs: SimpleNamespace(accepted=True, failure_attempt_count=0, max_attempts=3))
    monkeypatch.setattr(execution, '_job_heartbeat', lambda *_: nullcontext())
    monkeypatch.setattr(execution, '_build_dependencies', lambda *_args, **_kwargs: None)
    def unavailable(*_):
        raise ServiceRequestError('checkpoint_storage', 'temporarily unavailable', 503)
    monkeypatch.setattr(execution, 'run_ingest_graph', unavailable)
    result = execution.run_ingest_document(state['payload'].to_dict())
    assert result['status'] == 'queued'
    assert backend.failure['retry_message'] == state['payload'].to_dict()


def test_sparse_failure_keeps_saved_dense_work():
    from rag.ingestion.pipeline.indexing_stages import _resume_sparse_vectors
    from rag.shared.contracts.sparse import SparseVector
    class Sparse:
        model_name = 'test-sparse'
        def __init__(self, fail=False):
            self.inputs = []
            self.fail = fail
        def embed_many(self, texts):
            self.inputs.append(list(texts))
            if self.fail and texts[0] == '16':
                raise RuntimeError('sparse failed')
            return [SparseVector(indices=[int(text)], values=[1.]) for text in texts]
    state, deps = context()
    deps = replace(deps, sparse_embedder=Sparse(fail=True))
    _save_prepared_checkpoint(state, deps)
    _resume_dense_vectors(state, deps, state['embedding_texts'], lambda *_: None)
    with pytest.raises(RuntimeError, match='sparse failed'):
        _resume_sparse_vectors(state, deps, state['embedding_texts'])
    _, restarted = context(deps.backend, deps.checkpoint.storage)
    restarted = replace(restarted, sparse_embedder=Sparse())
    resumed = dict(payload=state['payload'], file_bytes=b'source')
    assert restore_prepared_state(resumed, restarted, _configuration_digest(restarted))
    _resume_dense_vectors(resumed, restarted, resumed['embedding_texts'], lambda *_: None)
    result = _resume_sparse_vectors(resumed, restarted, resumed['embedding_texts'])
    assert restarted.ollama.inputs == []
    assert restarted.sparse_embedder.inputs == [[str(i) for i in range(16,32)], [str(i) for i in range(32,40)]]
    assert [vector.indices for vector in result] == [[i] for i in range(40)]


def test_checkpoint_download_is_bounded_before_decoding(monkeypatch):
    from rag.ingestion.checkpoints.adapters import storage as module
    from rag.ingestion.checkpoints.service import CheckpointTooLarge
    from io import BytesIO
    class Response(BytesIO):
        def release_conn(self):
            pass
    response = Response(b'x'*10)
    storage = CheckpointObjectStorage(MinioConfig('unused', '', '', 'unused', False))
    storage._client = lambda: SimpleNamespace(get_object=lambda *_: response)
    monkeypatch.setattr(module, 'MAX_COMPRESSED_BYTES', 4)
    with pytest.raises(CheckpointTooLarge):
        storage.read(object_key='unused')
    assert response.closed


def test_interrupted_adoption_copies_remaining_references_without_overwriting_local():
    state, deps = context(count=1)
    _save_prepared_checkpoint(state, deps)
    _resume_dense_vectors(state, deps, state['embedding_texts'], lambda *_: None)
    prepared = deps.backend.get_checkpoint(job_id='job', stage_key='prepared')
    local_key = prepared.object_key.replace('/job/', '/next/')
    deps.checkpoint.storage.put(object_key=local_key, content=deps.checkpoint.storage.read(object_key=prepared.object_key))
    deps.backend.commit_checkpoint(replace(prepared, job_id='next', object_key=local_key))
    del deps.checkpoint.storage.values[prepared.object_key]
    assert deps.checkpoint.adopt_predecessor(job_id='next', document_id='doc', predecessor_job_id='job') == 1
    assert deps.backend.get_checkpoint(job_id='next', stage_key='dense:0:1') is not None
