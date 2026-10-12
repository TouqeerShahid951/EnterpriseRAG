# Summarization implementation plan

Status: core implementation complete on 2026-09-07. Deployment model quality
and latency evaluation remain release checks.

Based on the working-tree review on 2026-09-07. Preserve unrelated in-progress
changes. Recheck the relevant source before each implementation slice.

## Outcome and scope

Chat summaries should cover the requested authorized source scope, preserve
original evidence references, and state when processing is incomplete. Small
inputs use one synthesis call; larger inputs use section summaries, document
summaries, and, when requested, cross-document synthesis.

| Request | Evidence behavior |
| --- | --- |
| Factual QA | Existing hybrid retrieval and reranking |
| Whole-document summary | Enumerate authorized content in document order |
| Section/chapter summary | Resolve the section, then enumerate its content |
| Topic summary | High-recall hybrid retrieval, structural diversity, and bounded expansion |
| Summarize/compare selected documents | Summarize each document, then synthesize shared findings, differences, contradictions, and unique points |

The first release covers indexed document summaries. Live database execution,
GraphRAG community generation, and downloadable artifact composition keep their
existing owners. Mixed-source requests must retain their required source
assignments; they must not be silently redirected to a document-only summary.

## Ownership and compatibility

- Put summary planning, execution, intermediate models, and coverage policy in
  `backend/src/rag/query/summarization/`. Start with `models.py`, `planning.py`,
  `execution.py`, and `coverage.py` only where their responsibilities require it.
  Do not add a standalone service, queue, registry, or generic pipeline framework.
- Keep source scans behind `rag.retrieval.contracts`; Qdrant access and filter
  construction remain in the existing adapters/composition. Pass typed policy
  values and inference/retrieval dependencies into summary execution.
- Reuse current ingestion structure, inference clients, cancellation tokens,
  source anchors, faithfulness checks, and query history lifecycle.
- Preserve `/api/v1` request/response shapes, existing public `QueryIntent`
  values, SSE event names, citation links, CSRF, and permission enforcement.
  Summary scope is an internal plan property, not a new required HTTP field.
- Keep original source records separate from intermediate summaries. Never
  represent generated text as an original retrieved chunk.

## Phase 1 — Make coverage truthful at the final prompt boundary

Primary files: `query/answering/synthesis.py`, `query/query_stream.py`,
`query/nodes/retrieval_nodes.py`, and their current tests.

- [ ] Add the reproduced regression: 12 covered sources become 11 prompt
  contexts, but the current response still reports complete coverage.
- [ ] Make prompt preparation expose which original evidence units and text
  spans actually survive budgeting. Recompute coverage after dropping a source
  or truncating its text, and build completeness instructions from that result.
- [ ] Apply the same preparation result to ordinary and streaming responses,
  response coverage, and persisted history. Do not credit a whole source merely
  because a fragment or citation label survived.
- [ ] Keep structural coverage separate from factual grounding. A complete scan
  does not prove every important claim appeared in the answer.

Acceptance: removing the only evidence for a required unit always yields partial
or unknown coverage, including during streaming. Cases with sufficient context
retain complete structural coverage. This patch can ship independently.

## Phase 2 — Resolve summary scope explicitly

Primary files: `query/routing/intent_router.py`, `capability_planner.py`,
`routing_models.py`, `query/sources/source_resolution.py`, and summary planning.

- [ ] Add a typed internal summary plan containing mode (`document`, `section`,
  or `topic`), authorized document IDs, optional section selector/topic, and
  requested synthesis style. Multiple document IDs represent multi-document
  work; preserve comparison intent alongside summarization.
- [ ] Use the conversation-resolved query and selected documents first. Resolve
  named targets from visible sources. Ask for clarification when the target or
  section is ambiguous; never choose the first semantic hit as a substitute for
  an unresolved explicit target.
- [ ] Unify deterministic and LLM-planner interpretation. Recognize overview and
  “what is this document about”; treat chapter summaries as complete within that
  chapter; distinguish “summarize authentication” from a whole-document request.
  Cover negated summarization and ordinary explanatory QA as counterexamples.
- [ ] Activate summary execution from the typed plan rather than one response
  label. “Compare and summarize these three reports” must retain both behaviors.
- [ ] Keep selected IDs and group/clearance/lifecycle/temporal constraints binding
  through scope resolution, scans, expansion, and retries. Do not expose hidden
  document names in clarification or coverage messages.

Acceptance: a table-driven routing suite covers the example requests above,
selected and inherited documents, ambiguous titles, unavailable targets,
comparison plus summary, planner failure, and explicit mixed-source requests.

## Phase 3 — Enumerate complete, ordered source units

Primary files: `retrieval/contracts.py`, `retrieval/adapters/query_runtime.py`,
`query/qdrant.py`, `query/retrieval/query_retrieval.py`, and summary planning.

- [ ] Evolve the existing scan contract to return a typed result containing
  chunks, explicit completeness, and a stop reason. Carry status even when zero
  chunks were returned. Do not infer completeness from `len(chunks) < limit`.
- [ ] Extend retrieved chunks with available section, parent, numeric order, and
  generation metadata. Migrate the existing artifact scan consumer and tests in
  the same change; preserve its public output contract and warning semantics.
- [ ] Reuse one paginated scan implementation for query and artifact consumers.
  Keep the existing 5,000-chunk query safety cap initially and report truncation.
  Once document IDs are resolved, whole-document/section scans need no embedding
  query or relevance-based top-k selection.
- [ ] Order by document, page, and numeric chunk order. Read numeric suffixes from
  existing chunk IDs where valid; use a deterministic documented fallback for
  older records. Avoid requiring bulk reingestion merely to introduce ordering.
- [ ] Build non-overlapping source units using section/parent boundaries, then
  token-bounded splits. Use ordered page/chunk batches when headings are absent.
  Avoid counting overlapping parent text, child text, table rows, and cells twice.
- [ ] Create a source manifest before reduction: document/generation identities,
  expected units, original evidence references, scan status, and quality warnings.
  Revalidate access and active generation before emitting derived content; if the
  source changed, restart affected work within budget or stop with a clear reason.

Acceptance: scan completion and ordering are correct across pagination, a cap,
an empty timeout, multiple documents, missing headings, and legacy payloads.
Inaccessible, expired, inactive, and superseded content cannot enter a summary.
No original chunk IDs or stored vectors need to change.

## Phase 4 — Implement bounded hierarchical synthesis

Primary files: summary execution/models/coverage and existing inference and
answering helpers.

- [ ] If every required source unit fits the actual prompt budget, synthesize
  directly. Do not apply the ordinary 12-item evidence cap to this path.
- [ ] Otherwise map each bounded source group into a validated summary carrying
  claims and their original evidence IDs. Prompts preserve main findings,
  decisions, numbers, exceptions, risks, and relationships. Treat source text as
  data and reject malformed output and invented evidence references.
- [ ] Reduce within each section/document before cross-document synthesis. When
  inputs still exceed context, reduce another level. Require token-size progress
  at each level; stop explicitly if output fails to compress.
- [ ] Retain original evidence and server-owned unit lineage independently of
  model output. Validate each intermediate claim's references against its input;
  verify final claims against their cited original evidence, not summary text.
- [ ] Keep an explicit ledger of planned, processed, failed, and represented
  units. A model listing an input ID is not proof that its content was preserved.
  Check section representation and material omissions before final synthesis.
- [ ] Repair missing/failed units directly, with at most one repair attempt per
  unit and within the total budget. Preserve successful intermediate work during
  in-request retries. If work remains incomplete, produce a supported partial
  summary listing accessible omissions; abstain if no supported summary exists.
- [ ] Use the configured model/context limits, reserve output and prompt
  overhead, and bound every model call by the remaining stage budget. Start
  sequentially. Measure the deployed model to choose a documented total summary
  deadline with final synthesis/verification time reserved; do not give every
  batch a fresh full-request deadline.

Acceptance: a synthetic long document with distinct beginning, middle, and final
sections is fully represented; a large section requires multiple map calls;
multi-level reduction preserves provenance; one failed group cannot yield a
complete result; non-compressing output cannot cause an unbounded loop.

## Phase 5 — Integrate both query paths and topic coverage

Primary files: `query/graph.py`, `query/query_stream.py`, `query/nodes/`,
`query/service.py`, existing retrieval helpers, and chat progress labels.

- [ ] Branch to the summary workflow after source/conversation routing, before
  normal QA reranking and evidence truncation. Both graph runners call the same
  summary executor. Keep normal QA behavior intact.
- [ ] Stream progress during collection, section processing, and synthesis;
  stream final answer tokens only after required preparation. Reuse current SSE
  event shapes and expose plain-language progress in chat. Send bounded source
  previews and final cited sources, not one source event for every scanned chunk.
- [ ] Propagate cancellation through scans, map/reduce calls, repair, final
  synthesis, and verification. Preserve existing event ordering, final answer
  correction behavior, request idempotency, and history completion semantics.
  Test disconnects during an in-flight model call as well as between events;
  canceled work must not be persisted as a completed chat turn.
- [ ] For topic summaries, reuse existing dense/sparse hybrid search with a
  larger bounded candidate pool (start at 50 candidates), group by document and
  section/page, then select diverse groups within budget. Expand relevant
  sections inside the authorized target scope before using the same map/reduce
  executor. Add MMR only if evaluation shows structural grouping is insufficient.
- [ ] State topic coverage precisely: complete processing of selected topic
  evidence is not proof that every relevant corpus passage was discovered.
  Explicit “everything about X” requests require scanning the authorized scope
  for coverage assessment or an explicit partial/unknown coverage result.
- [ ] Ensure multi-document output distinguishes common findings, differences,
  contradictions, and unique points; do not silently flatten provenance across
  documents.

Acceptance: synchronous and streaming results agree on sources, coverage, and
status; canceling any stage prevents later calls; one document cannot disappear
from a multi-document summary; repeated near-duplicate topic hits cannot crowd
out other represented subtopics.

## Validation and release gates

- [ ] Add focused tests under `backend/tests/query/summarization/` plus affected
  routing, retrieval, answering, graph, stream, history, and artifact scan tests.
- [ ] Extend architecture checks for query-owned summary behavior, retrieval
  adapter boundaries, and unchanged public query/artifact schemas.
- [ ] Run focused checks first, then backend lint and the backend suite. Run
  frontend tests/typecheck/build for progress changes. If policy settings or
  deployment timeouts change, run configuration contracts and Compose validation.
- [ ] Compare ordinary QA and summary behavior on short/long documents, tables,
  missing headings, chapter targets, multiple reports with contradictions, topic
  variants, denied sources, and partial/failed ingestion. Include a provider
  smoke test against the configured offline model; unit tests do not establish
  summary quality or latency.
- [ ] Record source-unit coverage, citation validity, key-fact retention, model
  calls, input/output tokens, latency, cancellation latency, and partial reasons.
  Coverage describes indexed authorized content; missing OCR/ingestion content
  must not be silently counted as covered original-document content.
- [ ] Verify request and idle timeouts against the chosen summary budget. The
  current frontend proxy uses 300-second read/send timeouts; progress between
  batches does not protect against one silent overlong provider call. Enable the
  new route only after timeout and partial-result behavior pass on the deployment.
  Synchronous requests emit no progress bytes and must finish below that limit;
  choose the overall deadline with transport margin and verification reserve.
- [ ] Update the relevant query documentation and `docs/manuals/` sources; use
  the manual builder for generated manuals.

Delivery order: Phase 1 can ship first. Phases 2–4 plus the shared synchronous/
streaming integration form the first complete document/section summary release.
Topic coverage and multi-document comparison evaluation finish the broader plan.

Persistent summary caches, new workers, new model dependencies, custom diversity
scoring frameworks, and a new public summarization endpoint are deferred. Add a
durable asynchronous path only if measured target document sizes routinely
exceed the bounded request workflow; do not advertise complete processing for
those sizes before such a path exists.

## Completion notes

Implemented the first-class summary route, explicit summary modes, authorized
ordered scans with completion status, section filtering, structural grouping,
bounded map/reduce with one retry, original-evidence provenance, prompt-boundary
coverage reconciliation, per-document reduction, topic diversification,
cancellation checks, shared synchronous/streaming execution, bounded stream
source previews, and chat progress labels. Existing public query and artifact
response shapes remain unchanged.

Automated validation covers routing, direct and hierarchical summaries,
beginning/middle/end retention, failed groups, cancellation, section isolation,
multi-document representation, empty/truncated scans, scan metadata, artifact
compatibility, graph/stream branching, prompt trimming, architecture boundaries,
frontend types, and production build. Provider quality, production latency, and
the need for MMR or an asynchronous path require measurements from the deployed
models and representative private documents; those are operational release
checks rather than additional architecture.
