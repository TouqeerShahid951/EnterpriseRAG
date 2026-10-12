"""A killed interpreter resumes using only on-disk checkpoints in a new process."""
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from test_checkpoint_recovery import Model, Registry, context

from rag.ingestion.checkpoints.models import CheckpointDescriptor
from rag.ingestion.pipeline import graph
from rag.ingestion.pipeline.indexing_stages import _resume_dense_vectors, _save_prepared_checkpoint


class DiskRegistry(Registry):
    def __init__(self, root):
        super().__init__()
        self.path = root / 'registry.json'
        if self.path.exists():
            for row in json.loads(self.path.read_text()):
                item = CheckpointDescriptor(**row)
                self.values[(item.job_id, item.stage_key)] = item

    def commit_checkpoint(self, descriptor):
        result = super().commit_checkpoint(descriptor)
        self.path.write_text(json.dumps([asdict(d) for d in self.values.values()]))
        return result

    def get_job_status(self, *, job_id):
        return SimpleNamespace(status='processing', retry_of_job_id=None)


class DiskObjects:
    def __init__(self, root):
        self.root = root

    def put(self, *, object_key, content):
        path = self.root / object_key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def read(self, *, object_key):
        return (self.root / object_key).read_bytes()


class ProcessModel(Model):
    def __init__(self, root, phase):
        super().__init__()
        self.root, self.phase = root, phase

    def embed_many(self, texts, *, progress=None):
        with (self.root / 'calls.jsonl').open('a') as handle:
            handle.write(json.dumps({'phase': self.phase, 'stage': 'dense', 'texts': texts}) + '\n')
        if self.phase == 'first' and texts[0] == '16':
            os._exit(86)
        return super().embed_many(texts, progress=progress)


def run_worker(root, phase):
    prepared, deps = context(DiskRegistry(root), DiskObjects(root))
    deps = replace(deps, ollama=ProcessModel(root, phase), embedding_batch_size=16 if phase == 'first' else 8)
    def record(stage):
        with (root / 'calls.jsonl').open('a') as handle:
            handle.write(json.dumps({'phase': phase, 'stage': stage}) + '\n')
    def parse(state, _deps):
        record('parse')
        state['parsed_items'] = []
        state['parser_provenance'] = {'parser': 'test', 'page_outcomes': [{'page': 1, 'outcome': 'extracted'}]}
        return state
    def metadata(state, _deps):
        record('metadata')
        state['metadata'] = {'summary': 'source metadata'}
        return state
    def chunk(state, deps):
        record('chunk')
        for key in ('chunks', 'embedding_texts', 'claims'):
            state[key] = prepared[key]
        _save_prepared_checkpoint(state, deps)
        return state
    def embed(state, deps):
        state['vectors'] = _resume_dense_vectors(state, deps, state['embedding_texts'], lambda *_: None)
        return state
    graph.mark_processing = lambda state, _: state
    graph.download_file = lambda state, _: dict(state, file_bytes=b'source')
    graph.extract_text, graph.generate_metadata, graph.chunk_text = parse, metadata, chunk
    graph.embed_chunks = embed
    graph.upsert_qdrant = graph.activate_generation = lambda state, _: state
    state = graph.run_ingest_graph(prepared['payload'], deps)
    (root / 'result.json').write_text(json.dumps({'vectors': state['vectors'], 'metadata': state['metadata'], 'provenance': state['parser_provenance']}))


def test_fresh_process_resumes_after_16_committed_vectors(tmp_path):
    command = [sys.executable, str(Path(__file__).resolve()), str(tmp_path)]
    first = subprocess.run([*command, 'first'], capture_output=True, text=True, timeout=30)
    assert first.returncode == 86, first.stderr
    second = subprocess.run([*command, 'second'], capture_output=True, text=True, timeout=30)
    assert second.returncode == 0, second.stderr
    calls = [json.loads(line) for line in (tmp_path / 'calls.jsonl').read_text().splitlines()]
    resumed = [call for call in calls if call['phase'] == 'second']
    assert [call['stage'] for call in resumed] == ['dense', 'dense']
    assert [call['texts'] for call in resumed] == [[str(i) for i in range(16,32)], [str(i) for i in range(32,40)]]
    result = json.loads((tmp_path / 'result.json').read_text())
    assert result['vectors'] == [[float(i), 1.] for i in range(40)]
    assert result['metadata'] == {'summary': 'source metadata'}
    assert result['provenance']['page_outcomes'] == [{'page': 1, 'outcome': 'extracted'}]


if __name__ == '__main__':
    run_worker(Path(sys.argv[1]), sys.argv[2])
