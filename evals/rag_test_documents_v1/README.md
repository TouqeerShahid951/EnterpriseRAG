# RAG test documents v1

This package turns the mixed `RAG test documents` folder into a reproducible,
leak-free RAG benchmark and ingestion manifest.

## Outputs

- `BASELINE.md` — the first live benchmark result and Samsung candidate-fate
  proof captured without changing application configuration.
- `dataset.jsonl` — API-compatible answer/source evaluation cases.
- `ranking-gold.json` — companion retrieval/reranker gold that the current API
  schema cannot store without silently dropping fields.
- `corpus-manifest.json` — canonical, hash-pinned source and generated files.
- `exclusion-manifest.json` — duplicates, question sheets, unsupported files,
  temporary files, and negative/stress fixtures that must not enter the corpus.
- `generated-corpus/` — JSON derivatives of the useful XLSX/TXT evidence sources.
- `ingestion-results.json` — written by `ingest.py` after an ingestion run.

The question PDF and FIR HTML are dataset inputs only. They are intentionally
excluded from retrieval so the corpus cannot answer by finding the question
sheet itself.

The FIR gold includes CNIC-, phone-, and IMEI-shaped values copied from the
local test sources. Generated artifacts are ignored by Git and should remain
local until their synthetic provenance is confirmed or an approved redaction
policy is applied.

The Samsung cases use three document-bound evidence expectations: one each for
pages 51, 52, and 53, with page-specific anchors and full anchor recall. The
same spans appear in `ranking-gold.json`, which adds stage-specific retrieval,
reranker, and final-context thresholds without duplicating their source data.

## Build

```bash
PYTHONPATH=backend/src \
/Users/tabbasi/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
  evals/rag_test_documents_v1/build_dataset.py \
  --source-root "/Users/tabbasi/Desktop/_Organized Desktop/AI and RAG Projects/RAG test documents"
```

The build is strict: all 75 source-folder files must be classified, all hashes
are recomputed, the 54 FIR questions must match the supplied gold in order, and
the generated dataset must normalize through the application's importer.

## Ingest

Set `RAG_EMAIL` and `RAG_PASSWORD`, then run:

```bash
backend/.venv/bin/python evals/rag_test_documents_v1/ingest.py \
  --base-url http://127.0.0.1:3000 \
  --group-path /test
```

Use `--tiers core` for the answer-bearing benchmark corpus only. The full
manifest also includes distractor and OCR coverage files, some of which are
expected to enter human review on strict extraction-quality checks.

Ingestion is manifest-driven and one file per request. Existing complete
documents are skipped, upload conflicts are recorded, and existing failed
documents are not blindly retried. OCR/image-heavy files use the manifest's
`high_accuracy` preset; other files use `balanced`.

Dataset imports are immutable. An exact semantic match is reused; changed case
semantics create a hash-suffixed dataset version so historical runs keep their
original inputs.

## Smoke evaluation

Run the default four-case cross-domain check after the dataset import:

```bash
backend/.venv/bin/python evals/rag_test_documents_v1/run_smoke.py \
  --base-url http://127.0.0.1:3000 \
  --group-path /test
```

To isolate a particular case, repeat `--case-id` as needed. For example:

```bash
backend/.venv/bin/python evals/rag_test_documents_v1/run_smoke.py \
  --case-id samsung-equipment-001 \
  --output samsung-smoke-results.json
```

The runner verifies that the API accepted every requested case, persists the
last run payload, and exits nonzero for a failed, partial, cancelled, or timed
out run.

## Release gate

Run two full evaluations and check them together:

```bash
backend/.venv/bin/python evals/rag_test_documents_v1/run_release_gate.py
```

To check two already-launched runs, pass `--run-id` twice. The gate verifies the
local/remote dataset identity, exact gold/corpus hashes, all case denominators,
RAG configuration and reranker pins, retrieval/reranker diagnostics, semantic
judge and faithfulness coverage, citation resolution, and route-specific p95.
Missing evidence is a failure. In particular, the current text-free trace
must be paired with exact anchor-presence diagnostics to prove pre-rerank span recall.
Runtime image, prompt, active-generation, and host-profile pins must also be
exposed; the report names missing blockers instead of approving a release.

Set `APPLICATION_IMAGE_DIGEST` to the deployed API/evaluation-worker image
digest and `EVALUATION_HOST_PROFILE` to the approved hardware-profile ID before
launching pinned runs. Runs also freeze query policy, model identifiers, and the
visible current-document content-set hash. `active_generation` intentionally
remains unavailable until Slice 2 introduces the authoritative index-generation
pointer, so this baseline fails closed instead of treating document hashes as an
index-generation identity.
