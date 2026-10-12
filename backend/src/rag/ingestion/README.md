# Ingestion capability

This package owns the complete document-ingestion lifecycle. Runtime entrypoints
under `backend/apps/workers/document_pipeline` should only configure Celery and
call this package.

- `contracts.py` defines the producer/worker wire payload.
- `queue.py`, `recovery.py`, and `worker_control.py` manage dispatch and recovery.
- `folders/` owns the scheduled folder-ingestion vertical slice. Its
  `routes.py` and `schemas.py` define the HTTP contract; `service.py`,
  `scheduling.py`, and `dispatch.py` own use cases, recurrence rules, and
  due-run execution without importing FastAPI or global process settings.
- `folders/sources.py` defines source ports. Filesystem, MinIO, and persistence
  implementations live in `folders/adapters/` and are wired by
  `folders/dependencies.py`.
- `execution.py` builds worker dependencies and executes one ingestion job.
- `pipeline/` defines the ordered ingestion workflow.
- `checkpoints/` stores bounded, checksummed stage and embedding-batch artifacts
  in MinIO with PostgreSQL references fenced by the active ingestion lease. A
  redelivery restores committed prepared output and recomputes only missing
  dense or sparse ranges; an upload without a registry commit is ignored.
  Logical embedding ranges are saved with prepared output, so changing batch size
  does not discard completed ranges. Glossaries restore without embedding texts.
  Parser settings, provider/model identity, document inputs and current approved
  review contents determine compatibility. Embedding-model changes retain prepared
  text while invalidating that model's vectors; vectors also bind the prepared
  artifact checksum. Bump `pipeline/fingerprints.py:PIPELINE_OUTPUT_VERSION` after
  semantic parser, prompt, chunker or preprocessing changes. Providers that expose
  no immutable model revision require a fresh unlinked Reingest after replacing a
  model behind the same name and endpoint.
  Missing, corrupt and incompatible references are invalidated under the current
  job lease with an exact-reference comparison before recomputation. Storage
  connection/authentication failures use the existing bounded durable retry path.
  Gzip output is deterministic and both download and decoded sizes are bounded.
  The internal DELETE checkpoint endpoint must be deployed with the API before
  updated workers; artifact schema 2 rejects older artifacts and recomputes them.
  Linked retries copy only missing references; completed local copies do not
  depend on predecessor objects again, even if copying was interrupted.
- `parsers/`, `chunking/`, `metadata/`, and `indexing/` implement pipeline work.
  Chunking keeps parsed headings, paragraphs, list provisions, tables, and
  worksheet sections as logical blocks; size limits may split an oversized
  block but must not create an orphan heading or cross a logical section.
  CSV and XLSX parsers emit the same table items used by document tables, so
  spreadsheet rows retain the standard indexing, access, and retrieval behavior.
  Spreadsheet schema reviews are stored with document metadata and reapplied by
  ordinary reingestion; they are not a separate connector lifecycle.
- `publication/` stages and verifies a replacement index, then atomically switches
  the document's active generation before asynchronous retirement.
- `adapters/` contains concrete clients for storage, inference, and backend APIs.
- `ops/` contains ingestion-specific command-line operations.

Keep contracts and quality rules free of runtime I/O. Keep business behavior in
this package rather than in Celery task entrypoints or API routes. Add another
subdirectory only when a cohesive area has enough code to justify it.

## Parser integrity

PDF page fusion preserves the original native page until a replacement passes
coverage and provenance checks. Parser provenance records an outcome for every
source page (`extracted`, `confirmed_blank`, or `failed`). A failed page raises
`pdf_incomplete` before indexing; fix the extraction dependency/source and retry.
No partially extracted replacement is published as a complete document.

Heading paths preserve DOCX/authored and PDF bookmark levels, infer numbered
sections and native font levels, and flag unresolved hierarchy. Table captions
remain attached to tables without becoming nested document sections. Docling
page spans are retained through review serialization and citation targets.

PDF image OCR absorbs duplicate plain OCR blocks only when their full text
matches (allowing whitespace differences) and their boxes lie within the image
on the same page. Each image transcription occurrence can cover only one block.
Tables, headings, native text, differing text, and uncertain locations remain
intact. Consolidated entries retain source spans and the weakest confidence;
one OCR approval edits their transcription, while the generated image description
is shown separately and remains excluded from original-text quotation evidence.
Image-selection resumption also passes through the OCR confidence gate.
Existing review batches retain their saved shape; new ingestion or reingestion
uses this consolidation without rewriting completed reviews or active indexes.

Source highlights use the citation targets saved with each indexed chunk:
PDF page regions and exact rendered text for Word documents. Reingest documents
indexed before citation targets were introduced to regenerate their locations.
Word text targets use adjacent document text for context; appended image
descriptions are excluded because they are not rendered as document paragraphs.
The Word viewer preserves spaces between formatting runs and highlights all
matched targets in the cited chunk, including paragraphs following a heading.
PPTX text and chart regions are converted from native slide units into the
stored slide image's pixel coordinates, including each provenance span. Embedded
pictures retain their position on that slide. Full-slide visual interpretations
highlight the whole slide; they do not imply an exact text quotation. Reingest
existing presentations after deploying these coordinate fixes.

JSON table views retain their underlying source leaves and sibling metadata;
large scalar collections are split instead of discarded. Presentation chart
rows preserve plot, series, category or X/Y coordinates, and bubble sizes;
missing axes fail explicitly. Spreadsheet tables preserve common display
formats, raw values and number formats, and formula expressions with cached
results when present. Cached results are not recalculated. Unsupported Excel
formats are retained explicitly rather than approximated; inferred headers are
flagged and can be corrected through the existing schema review.

Parser fixes affect new ingestion and reingestion. Existing generations retain
their original extraction until a replacement is successfully published. Start
with a small representative sample before reingesting a large collection.

Regression coverage lives in `backend/tests/ingestion/test_parser_integrity.py`
and the format-specific parser tests. Query section-scope regressions live in
`backend/tests/query/test_hierarchical_summarization.py`.

Checkpoint regression coverage includes `test_checkpoint_recovery.py`,
`test_checkpoint_fencing.py`, and `test_checkpoint_process_restart.py`. The latter
terminates a separate interpreter after 16 vectors are committed and resumes in a
fresh interpreter with only file-backed test stores. It verifies stage skipping,
ordered vectors and provenance; it does not replace a controlled deployment test
against MinIO, PostgreSQL and Qdrant.
