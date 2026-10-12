# Operational RAG analytics: implementation plan for Luna

Status (2026-09-09): The A/B analytics slices, nine review fixes and heartbeat-based abandoned-query detection are deployed to the local Compose environment. API, query-api, frontend, query-analytics-maintenance and evaluation-worker are healthy; authenticated analytics/query checks passed. Remaining broader release checks are listed below; Milestones C and D remain planned.
Prepared: 2026-09-08. Audience: Luna implementing this repository incrementally.

## 1. Product objective

Build a new **Analytics** page for historical production RAG activity. Help a
Platform Admin answer: what is happening, where is it failing, and what changed?
There is no golden production dataset. Report operational observations and
automated evidence checks; do not label these as absolute answer accuracy,
router accuracy, retrieval recall, or a probability that an answer is correct.

The useful interaction is:

```text
Trend or outcome segment
  -> filtered historical query list
  -> one execution's route and timings
  -> retrieved/reranked/selected evidence
  -> verification result and available authorized content
```

Every chart must have a diagnostic purpose, an explicit population and unit,
and either a working drill-down or a clear explanation of its limits.

### Scope and navigation decisions

- Create one page with eventual **Overview**, **Queries**, **Retrieval**, and
  **Performance** tabs. Initially ship Overview and Queries, including an
  inspector within the page. Add tabs when their data is implemented.
- New route ID: `operational-analytics`; URL: `/operational-analytics`; visible
  label/title: `Analytics`. Put its navigation entry in **Operate**.
- Preserve `/evaluations`, its RAG Evaluation page, datasets, runs, and live Query
  Tracker. Preserve the legacy `analytics` route ID and `/analytics` alias to
  `evaluations`. That alias already exists; do not silently repurpose it.
- Use the existing Ingestion Activity/Pipeline Health, Document Overview/Library,
  System Audit, and System Overview resource views for their detailed workflows.
  Add analytics to their owners later; do not create nine duplicate pages.
- Initial access is **Platform Admin only**, on both frontend and backend.
  Space Admin/Audit Viewer access is a later, explicitly scoped extension.
- This plan authorizes no new automatic production actions: charts and review
  flags do not change routing thresholds, delete documents, or launch queries.

### Delivery milestones

| Milestone | Steps | Deliverable |
| --- | --- | --- |
| A: operational foundation | 0–9 | Durable production summaries, Overview, query list and metadata inspector, bounded retention, regression checks |
| B: evidence diagnostics | 10–12 | Retained evidence lineage, Retrieval/Performance tabs, qualified faithfulness and citation analytics |
| C: existing operational pages | 13–15 | Ingestion/corpus analytics, security dimensions, infrastructure history |
| D: feedback and investigation | 16–17 | Explicit feedback, labeled behavioral signals, cohort comparisons |

Implement milestones in order. Do not scaffold later APIs, empty tabs, services,
or schema columns solely because they appear in the roadmap. Steps 13–17 remain
planned; completing the A/B slices does not complete this plan.

## 2. Read first and preserve current work

Before each implementation slice:

1. Run `git status --short`. The working tree was heavily modified when this plan
   was written. Preserve unrelated changes; do not reset, stage, or commit them.
2. Read root `AGENTS.md`, `PRODUCT.md`, `README.md`, `backend/README.md`, any nested
   instructions, and the owning feature README. This document does not override
   repository dependency boundaries.
3. Recheck the actual files below. Paths and observations describe the working
   tree on the preparation date, not a verified production deployment.
4. Find every caller before modifying query execution, history, trace capture,
   authorization, or response serialization. Cover synchronous, streaming,
   tracker, evaluation, and artifact-submission paths as applicable.

### Existing implementation to reuse

All paths in code tables are repository-relative. They are reading/placement
guides, not permission to refactor unrelated work.

| Area | Existing files | What exists / limitation |
| --- | --- | --- |
| Product/routes | `frontend/src/routes/routes.ts`, `frontend/src/app/App.tsx` | Central route/access/navigation registry and lazy page composition; `/analytics` aliases evaluations |
| Current overview | `frontend/src/features/overview/pages/PrudentiaPlannedPage.tsx`, `components/WorkspaceActivity.tsx`, `components/SystemResources.tsx` | Corpus summaries, audit event categories, live resource readings; these are not query history analytics |
| Query lifecycle | `backend/src/rag/query/service.py`, `execution_routes.py`, `query_stream.py`, `graph.py`, `state.py` | Shared execution, SSE lifecycle, node timings, cancellation and history writes |
| Response/history | `backend/src/rag/query/schemas.py`, `chat_history_models.py`, `adapters/chat_history_postgres.py` | Completed responses save status, intent, sources, latency and faithfulness; missing failures and deletable history make this insufficient as an analytics ledger |
| Rich operational events | `backend/src/rag/query/routing/routing_logs.py` | Start/complete/error, detailed intent, routing, budgets and score summaries primarily emitted as logs |
| Retrieval lineage | `backend/src/rag/query/retrieval/retrieval_trace.py`, `nodes/retrieval_nodes.py`, `query/analytics/service.py` | Production analytics reuses the existing five-stage trace, preserves generation-aware candidate identity and score fields, and stores only bounded text-free diagnostic rows |
| Tracker/evaluations | `backend/src/rag/evaluations/query_tracker_routes.py`, `case_execution/diagnostics.py`, `runtime_pins.py` | Live diagnostic trace, persisted evaluation diagnostics, reproducibility ideas; not the production analytics owner |
| Verification | `backend/src/rag/query/nodes/response_nodes.py`, `answering/faithfulness.py`, `backend/src/rag/shared/contracts/evidence.py` | Model/deterministic/fallback checks, skipped/failed states, evidence windows; not a complete verdict ledger for every factual claim |
| Retrieval scores | `backend/src/rag/query/qdrant.py`, `reranker.py`, `reranking/` | Hybrid search uses RRF fusion; raw dense and sparse component scores are not independently retained by the existing trace |
| Ingestion | `backend/src/rag/ingestion/README.md`, `job_models.py`, `monitoring.py`, `adapters/job_postgres_search.py` | Durable jobs, errors, attempts, provenance, timestamps and authorized summaries |
| Corpus | `backend/src/rag/documents/models.py`, `overview.py`, `backend/src/rag/ingestion/indexing/payloads.py` | Lifecycle/generation identity, chunk hashes and quality flags; no ready corpus-wide token histogram |
| Resources | `backend/src/rag/deployment/README.md`, `resource_metrics.py`, `adapters/resource_metrics.py`, `adapters/gpu_metrics.py` | Current host-visible CPU/memory/disk and supported NVIDIA readings; no retained resource time series |
| Authorization | `backend/src/rag/auth/dependencies.py`, `permissions.py`, `document_access.py`, `backend/src/rag/query/route_access.py` | Existing account, group, clearance and query-source access rules |
| Schema/contracts | `backend/src/rag/bootstrap/schema.py`, `backend/tests/architecture/` | Idempotent bootstrap and enforceable ownership/public API contracts |

Useful starting searches:

```bash
rg -n 'answer_query|execute_query|stream_query|append_completed_turn' backend/src backend/apps backend/tests
rg -n 'capture_retrieval_trace|log_query_|record_node_timing' backend/src/rag
rg -n 'analytics|evaluations|canonicalRoute|visibleNavigation' frontend/src
rg -n 'faithfulness_status|support_status|answer_status' backend/src/rag/query backend/src/rag/shared/contracts
```

## 3. Architecture and implementation defaults

### Capability ownership

Production query analytics belongs to **`rag.query`**. Use a cohesive
`backend/src/rag/query/analytics/` subpackage for this workflow. Keep concrete
persistence under the query feature's `adapters/`. Ingestion, documents, audit,
and deployment continue to own their data and application rules.

Suggested placement; only create entries a completed slice needs:

```text
backend/src/rag/query/
  analytics/
    models.py           # Analytics records, enums and filter values
    repository.py       # Narrow production analytics storage/read contract
    service.py          # Lifecycle rules and aggregate result policy
    schemas.py          # Analytics-only HTTP DTOs
    routes.py           # Thin Platform Admin HTTP endpoints
    dependencies.py     # Wire query-owned adapters and configuration
    schema.py           # Idempotent query analytics schema
  adapters/
    analytics_postgres.py
    analytics_memory.py # Used by existing memory runtime/tests
  ops/
    analytics_maintenance.py

backend/tests/query/analytics/
frontend/src/features/analytics/
  pages/PrudentiaAnalyticsPage.tsx
  components/           # Filters, charts, query table, inspector as needed
  state/                # URL filter state and query hooks as needed
  models/               # Presentation mapping and pure display rules
frontend/src/types/api/analytics.ts
frontend/src/lib/api/contracts/analytics.ts
frontend/src/styles/analytics.css
```

Routes depend on services/contracts, not concrete adapters. Application policy
must not import FastAPI, Celery, or global `Settings`. Pass typed configuration.
Compose HTTP routes through the existing query aggregate or API composition,
ensuring the resulting URL matches section 6 and is registered only once.

Frontend analytics must not import internal components/state from evaluations,
chat, documents, or overview. Extract a genuinely shared presentation primitive
only when two actual callers need it. Use existing feature APIs for cross-feature
data. Do not use the evaluation repository as production telemetry storage.

### Storage, collection and limits

- Use existing PostgreSQL and installed Python/React tooling. No new broker,
  analytics database, tracing platform, chart dependency or worker for milestone A.
- Capture lightweight summaries for every eligible execution, not a sample.
  Detailed trace retention is separate and starts in milestone B.
- Proposed initial retention: execution summaries/timings **30 days**, detailed
  candidate lineage **7 days**. These are implementation defaults, not an existing
  organization retention policy. Document and validate overrides through normal
  configuration ownership; do not silently change chat or audit retention.
- Default view: last **7 days**; offer **24 hours**, **30 days**, and custom within
  retained history. Store UTC. Start with explicit UTC daily/hourly buckets and
  label the timezone; do not silently group by the API host's local timezone.
- Initial maximum request window: 30 days; maximum 1,000 buckets; query-list page
  size 50, maximum 100. Validate the limits server-side and expose retention bounds.
- Read-only dashboards refresh at most every 30 seconds while visible. No SSE
  subscriptions or background polling for hidden analytics tabs in the first cut.
- Do not run additional model calls, duplicate retrievals, or corpus scans to
  populate the first dashboard.

### Privacy and access defaults

- Platform Admin can inspect operational metadata for recorded workspace
  executions. This is an explicit new analytics permission boundary; test it.
- Query/answer text, SQL, evidence text, prompts, and exception strings do not
  belong in summary rows or generic logs. Use safe codes and identifiers.
- Do not expose another user's saved conversation through the ordinary
  owner-scoped chat-history API. Initial inspector shows cross-user metadata;
  content is available only through an existing authorized owner contract.
  Otherwise show `Conversation content restricted`.
- An own-session link still checks current user, session ownership and permission
  version. Do not return text merely because the analytics row contains its ID.
- Evidence/title/source previews require current document or connector access,
  clearance, lifecycle and generation checks. Missing, revoked, retired, or expired
  content yields an explicit unavailable state. Never substitute a new chunk at
  an old document/chunk ID after reingestion.
- A future cross-user answer-review permission and governed answer snapshots are
  separate work. The initial metadata inspector is deliberately limited; do not
  describe it as full forensic replay.
- Use server-known user IDs for distinct-user counts. Do not trust caller-supplied
  user/model/origin fields. Do not copy all account group memberships into every
  usage count: requested scope and evidence-source groups are different dimensions.
- Reuse canonical clearance values, including `COSMIC_TOP_SECRET`, from
  `rag.shared.contracts.clearance`; the illustrative four-level list is incomplete.

## 4. Measurement contract: implement these definitions first

### Execution identity and populations

One **execution** is one server invocation of the query workflow, linked to a
server-generated request/execution identity. Internal retrieval retries and node
reruns stay within it. A new HTTP submission is a new attempt even if it reuses a
client request ID; an idempotent storage retry of the same execution is not.

Keep `client_request_id` as a correlation field, not a global uniqueness key.
It is scoped by caller/session and has existing history conflict/clarification
semantics. Do not change those semantics or add query replay as an analytics fix.

Record origin (`chat`, `query_tracker`, `evaluation`, `other_internal`) and work
kind (`answer`, `artifact_submission`) using server-owned call context. Default
analytics population is `origin=chat`, `work_kind=answer`.

For public transport failures, keep one request record even when execution never
starts. Eligible query counts require an authenticated actor and a schema-valid
query request. An authenticated, valid request denied by query/group/source
authorization is eligible and has outcome `access_denied`. Unauthenticated or
malformed requests are separate request diagnostics; do not inflate query users
or answer-rate denominators with them. Preserve normal status/error responses.

An HTTP request that starts an execution uses the same analytics lifecycle row;
boundary and service hooks enrich/finalize it, not two independently counted rows.
Direct tracker/evaluation calls get their own server-generated identity and origin.

### Terminal outcomes

Keep outcome distinct from verification and degradation:

| Outcome | Definition |
| --- | --- |
| `complete` | Final answer status is complete |
| `partial` | Final answer status is partial, including verification fallback responses |
| `clarification` | User must clarify intent/source/scope |
| `abstained` | Workflow deliberately did not answer based on its evidence/policy decision |
| `system_error` | Workflow failed without a normal terminal answer; safe error code retained |
| `access_denied` | Explicit query/group/source authorization rejection |
| `cancelled` | Observed user cancellation/disconnect before terminal completion |
| `interrupted` | A previously started execution is reconciled after confirmed abandoned execution/deadline expiry |
| `artifact_submitted` | An asynchronous artifact job was accepted; not a finished answer/artifact |

In-flight executions have no terminal outcome. Late duplicate events cannot
replace a successful terminal result with cancellation. An uncertain abandoned
record stays visibly unresolved until a safe reconciliation rule applies.
An SSE HTTP 200 with an error event is still a workflow error. A provider error
recovered into a delivered answer keeps that answer's outcome and a separate
operational-failure/degraded flag; do not erase the failure or double-count it.

### Metric dictionary

All rates return numerator, denominator, and nullable value. Zero denominator
means unavailable, not zero percent. Always return the observation count for
percentiles and scores. Unless otherwise stated, metrics share the selected
origin/work-kind/access/time filters and cohort by request start time `[from,to)`.

| Metric | Definition and eligibility |
| --- | --- |
| Queries | Count eligible execution attempts started in the window; list in-flight count separately |
| Unique querying users | Distinct authenticated actors among those attempts; not logged-in users or distinct audit actors |
| Complete-answer rate | `complete / terminal eligible answer executions`; partial, clarification, abstention, denial, error, cancellation and interruption remain in the denominator |
| Abstention rate | `abstained / same terminal denominator`; system errors remain separate |
| System-error rate | `system_error / same terminal denominator`; show interruption and recovered failure counts separately |
| Verification coverage | Checked / check-applicable terminal answers; applicability is an explicit recorded flag, not inferred from a score; display skipped, pending and failed counts separately |
| Automated faithfulness | Mean existing score only where `faithfulness_status=checked`; segment by method/policy/model/version; display checked sample count and coverage alongside |
| Answer completion latency | Server request-boundary duration to final answer/verification readiness for complete/partial/clarification/abstained responses; label as server latency, excluding browser/network rendering |
| Terminal duration | Boundary duration to any terminal outcome; analyze errors/cancellation separately from answer latency |
| Time to first answer token | Boundary start to first nonempty answer token; exclude trace/progress/warning events; unavailable when no answer token emitted |
| Stage latency | Per-execution total of a named stage across retries; distinguish not-run from zero; show attempt detail in inspector |
| Route distribution | Resolved source mode/capabilities, not requested `auto`; conversation-only, graph and rejected/unknown paths must not be mislabeled as document RAG |
| Intent distribution | Internal final intent/response mode; preserve public intent separately; unknown/early exits are explicit |
| Top reranker score | Maximum finite raw reranker score within a defined stage/attempt; no score is null; separate model versions and adjusted scores |
| Retrieved documents/query | Distinct `(doc_id,generation_id)` in authorized retrieved candidates; define last attempt vs union of attempts explicitly |
| Citations per answer | Count distinct valid source references actually cited by the final answer, not `len(response.sources)` |
| Evidence utilization | Distinct supplied evidence units referenced in delivered answer / distinct evidence units actually sent to generation; null without a reliable identity mapping |
| Rank movement | Mean absolute before/after rank difference for candidates present in both compared stages; dropped/added candidates counted separately |
| Document retrieval share | Executions retrieving document / eligible retrieval executions; document shares can sum over 100% because one execution can retrieve many documents |
| Never retrieved | Use label `Not observed retrieved in selected window`; only claim complete-window absence when telemetry coverage and document eligibility are known |

Implementation cautions:

- Existing `faithfulness_score=0` can mean skipped. The current judge may use
  deterministic, AI-assisted, or fallback checks. A semantic fallback evidence
  window is not automatically a supported citation.
- The current score is based on citation-bearing claim fragments and unfounded
  claims. Do not display it as a complete supported/unsupported/unknown claim
  percentage. Step 12 introduces that additional record if needed.
- Verification can replace the evaluated draft with a partial delivered answer.
  Identify score subject (`evaluated_draft` vs `delivered_answer`) and whether an
  answer was replaced. Do not attribute draft scores to replacement text.
- Hybrid search currently returns RRF fusion scores. Dense, sparse and fusion
  scores have different semantics and scales; never put them in one 0–1 histogram.
  Label sparse scores BM25 only when the configured implementation warrants it.
- The verifier is not necessarily a per-chunk acceptance filter. Use actual
  existing trace stages and skipped statuses. Summarization can follow another
  path; missing stages must not be represented as evidence rejection.
- Summing stage P95s does not yield request P95. Do not average daily percentiles
  into monthly percentiles. Use raw durations initially, with PostgreSQL
  `percentile_cont`, across the selected population. Stacked timing views use an
  individual execution or additive means over the same execution cohort; show
  stage percentiles as separate comparisons.
- Low-score flags require a known model/stage-specific policy threshold. Reuse
  applicable runtime thresholds; otherwise leave that review reason unavailable.
  Do not invent a universal score such as 0.7.

## 5. Data design for the first slices

Finalize exact names in step 1. Use typed columns for fields used in filters,
ordering, or common aggregates, and bounded versioned JSON only for compact
variable details. Do not persist an entire QueryContext or RAGResponse blob as
the analytics model.

### Execution summary (milestone A)

| Group | Required information |
| --- | --- |
| Identity | Server execution/request ID, optional existing trace ID, client request ID, session/turn reference, schema version |
| Population | Origin, work kind, authenticated/schema-valid eligibility flags |
| Time/state | Received/started/finished UTC timestamps, lifecycle state, reconciliation deadline where supportable |
| Access | Server actor ID, permission version at execution, validated selected group or `all_authorized`, actor clearance snapshot |
| Outcome | Terminal outcome, existing answer status, degraded flag, normalized safe reason, retry/reroute count, recovered operational-failure codes |
| Routing | Requested/resolved source mode, initial/final internal intent, public intent, response mode, bounded capability/source identifiers |
| Timing | Server terminal/answer duration, existing pipeline latency, first-token duration; unknown values nullable |
| Verification | Applicable flag, status, method, safe fallback category, score, subject, answer-replaced flag, unfounded-claim count |
| Evidence summary | Available retrieved/final/context/cited counts with explicit stage/attempt identity and availability, top reranker score/type |
| Reproducibility | Effective model IDs, selected nonsecret configuration digest, prompt-policy version, image/build digest when supplied |
| Integrity | Capture status/completeness, start/finalize version or guarded state transitions; no unsupported exactly-once claim |

Keep repeated node timing entries in a query-owned child table or bounded JSON
with a schema version. Select one representation based on the real aggregate
queries, not a generic event framework. Preserve ordinal/attempt identity so
duplicate writes cannot duplicate timing samples.

Suggested indexes: unique server execution ID; `(origin, work_kind, started_at,
execution_id)` for default browsing; add group/outcome indexes only when actual
queries and `EXPLAIN` justify them. Use parameterized SQL and constrained sort
fields. Count totals from all matching rows, never just the visible page.

Do not enforce one group per execution's evidence. Requested scope and document
ownership/sharing are separate. Later candidate/document observations carry
their own source/group/generation identity.

### Evidence details (milestone B)

Store stage name, attempt, stage status, candidate rank, stable point/document/
generation/chunk identity, score type/model, raw and adjusted reranker scores,
selection/deduplication reason where known, and sent/cited mappings. Preserve
unavailable/truncated state and counts before any diagnostic cap.

The existing trace serializer excludes evidence text but still carries document
titles and freeform fields. Define an analytics allowlist rather than treating
`to_row()` as automatically safe for indefinite retention or unrestricted output.
Do not persist `evidence_text` or raw reranker errors. Details can expire while
summary counts remain; responses explain that state.

Full candidate tracing is disabled by default in normal chat today. Enable
bounded capture deliberately in step 10 and measure its overhead. If cap or
sampling prevents complete document/rank observations, mark those metrics partial;
do not extrapolate exact totals. Always preserve lightweight counts independently.

### Collection failure policy

Analytics must not change query authorization, answer content, or existing
service availability semantics. Use bounded persistence operations. Catch only
recognized telemetry storage failures at the telemetry boundary, emit a safe
structured operational error, and continue the query. Do not catch and suppress
query failures under that policy. Failed maintenance exits nonzero.

This policy means outage periods can have missing telemetry. State that limitation
explicitly. Record capture-gap/recovery information where possible, surface stale
or unknown coverage, and never claim 100% capture from stored rows alone. A
process-local counter is not a reliable multi-replica capture ledger. Start with
observable bounded writes; do not add an unbounded in-memory retry queue, local
content spool, or one background job per query to claim losslessness.

## 6. Proposed HTTP and frontend contracts

Backend base: `/api/v1/admin/query-analytics`. All routes require the existing
Platform Admin dependency. These are additive APIs; preserve query/SSE contracts.

| Endpoint | Milestone | Result |
| --- | --- | --- |
| `GET /summary` | A | Counts, nullable rates, eligible denominators, available score/latency summaries and capture metadata |
| `GET /series` | A | Bounded UTC buckets for volume/outcomes/latency; allowlisted dimensions only |
| `GET /executions` | A | Filtered, stable paginated metadata rows and total |
| `GET /executions/{execution_id}` | A/B | Metadata/timings initially; authorized retained evidence lineage in B |
| `GET /retrieval` | B | Stage/score/rank/document aggregates with explicit eligibility |
| `GET /performance` | B | Stage percentiles and cohort comparisons; no duplicated infrastructure collector |

Common filters: `from`, `to`, `bucket=hour|day` for series, `origin`, `work_kind`,
validated `group_path`, `user_id`, terminal `outcome`, `source_mode`, internal
`intent`, model/configuration identity when captured, and an allowlisted
`review_reason`. Use the same filter object/predicate in summaries, series and
lists. Detail authorization is independent of the list that linked to it.

List uses `limit` and `offset` to match current endpoint patterns, with stable
`started_at DESC, execution_id DESC` ordering. Return `as_of` and reuse it across
pages in one browsing session to exclude newly started rows until refresh. Do
not promise a database snapshot of mutable in-flight rows. Cursor pagination can
replace this only if measured volume/concurrency calls for it.

Every aggregate response includes normalized filters, `as_of`, effective retained
window, timezone, schema version, population count, measurement coverage, and
data status (`available`, `empty`, `partial`, `unavailable`). A retention-clipped
request must be explicit; malformed/out-of-bounds filters return validation errors.
Zero-volume buckets are zero counts and null latencies, not fabricated samples.

Use existing structured error conventions for invalid filters, forbidden access,
missing execution, unavailable storage and expired details. No arbitrary SQL
group-by/sort fragments or arbitrary metric expressions accepted from clients.

Frontend contracts live in `lib/api/contracts/analytics.ts`, use the existing
`apiClient` module pattern, and preserve barrel exports in `contracts.ts` and
`types/api.ts`. Features never call raw `fetch`. Encode path identifiers and
build parameters with `URLSearchParams`.

URL state example:

```text
/operational-analytics?tab=queries&outcome=abstained&from=...&to=...&execution=...
```

Preserve filters when opening/closing an inspector and navigating back. Avoid
putting query/answer text in URLs. Validate URL values; browser parsing does not
replace server validation. Include normalized filters and access identity in
React Query keys; clear sensitive cached details when auth/permissions change.

## 7. Ordered implementation steps

### Step 0 — Establish the baseline

Read the files in section 2 and trace current callers. Record existing test
failures separately from analytics changes. Confirm both API replicas use the
same query code and storage. Inspect current route aliases and available chart
primitives. Do not install dependencies or inspect production query contents.

Deliverable: a short baseline note appended to the implementation log below.

Acceptance:

- [ ] Existing unrelated modifications identified and preserved.
- [ ] Current sync/SSE/tracker/evaluation/artifact call paths identified.
- [ ] Route alias compatibility and access defaults understood.

### Step 1 — Define the measurement and persistence contracts

Implement query-owned models/configuration and the narrow repository operations
needed to start/finalize/read an execution. Translate sections 4–5 into explicit
enums, nullable fields and validation. Decide the timing storage representation
using actual summary/list/detail SQL needs. Avoid a generic event bus or registry.

Model transport request admission separately from query outcome; a request may
fail before its actor or query is known. Implement the terminal-state transition
rules before connecting to runtime I/O. Use an injected clock where needed.

Acceptance:

- [ ] Duplicate finalization is idempotent; late cancellation cannot overwrite completion.
- [ ] Internal retries do not increment query volume.
- [ ] New invocations sharing client request ID remain distinct attempts.
- [ ] Unknown, skipped, zero, in-flight, and interrupted are distinct.
- [ ] Score/status/subject and actor/request validity rules have focused tests.

### Step 2 — Add durable storage and bootstrap

Implement Postgres and the runtime-compatible memory adapter. Register feature
schema creation/repair through `rag.bootstrap.schema`. Use additive DDL, finite
numeric constraints, guarded terminal updates and atomic summary/timing writes.
Do not alter or backfill the chat tables as part of this schema change.

Acceptance:

- [ ] Bootstrap succeeds on an existing database and on a second invocation.
- [ ] Start/finalize writes survive repository re-instantiation.
- [ ] Duplicate writes/concurrent finalization cannot duplicate rows or stage samples.
- [ ] Multi-replica writes use database uniqueness/state guards, not a Python lock.
- [ ] Invalid persisted payload versions fail explicitly or return an explicit unsupported detail state.
- [ ] Memory and Postgres adapters agree on filtering/state behavior.

### Step 3 — Instrument query execution once

Wire lifecycle recording into the shared query service/state and boundary
composition. Trace all callers before editing. Reuse node timings and route
decisions already computed in memory; do not parse container stdout for normal
analytics ingestion. Keep existing operational logs.

Capture origin at server callers, including tracker/evaluation invocations;
do not infer origin from query wording or trust browser input. Preserve artifact
job submission semantics and classify its outcome/work kind separately.

Snapshot effective model IDs and an allowlisted nonsecret query configuration
digest at execution time. Reuse public query configuration ownership; do not
import evaluation-private runtime pin helpers or enumerate/hash the whole corpus
for every request. Store unavailable build identity as null.

Acceptance:

- [ ] Sync and streaming success each produce exactly one execution record.
- [ ] Tracker/evaluation traffic is excluded by default and separately filterable.
- [ ] Partial, clarification, abstention, recovered failure and artifact submission map correctly.
- [ ] Existing answer/SSE payloads, latency fields and history idempotency remain compatible.
- [ ] Telemetry outage produces a safe operational signal without swallowing a query exception or changing its answer.

### Step 4 — Cover boundary failures, SSE completion and cancellation

Service-only instrumentation misses authentication/schema/access rejection.
Add narrow query-request boundary observation, composed by API startup and owned
by query HTTP support. Reuse existing auth/error handling rather than installing
a competing global error policy. If ASGI middleware is needed, keep it scoped to
the query routes and preserve streaming; never buffer response bodies to inspect
SSE or read/log the request body twice.

Pass known admission/outcome metadata from validated dependencies/routes to the
same lifecycle row. Unknown actor/source remains unknown. Service finalization
owns workflow outcome; boundary observation adds duration/transport state without
overwriting it based only on HTTP status.

Measure first nonempty answer token and final answer readiness separately.
Cancellation can be triggered through generator close/disconnect without a normal
`Exception`; cover `finally`/cancellation paths. Persistence errors during cleanup
must not replace the original error. Do not classify a disconnect after a completed
answer as cancelled.

Acceptance:

- [ ] Authenticated group/source denials counted with safe structured reason codes.
- [ ] Unauthenticated/malformed requests remain outside answer-rate/user denominators.
- [ ] SSE error after HTTP 200 records `system_error`.
- [ ] Disconnect during retrieval/generation records cancellation when observed.
- [ ] Completion followed by disconnect remains complete.
- [ ] Missing terminal records are visible; interruption is not guessed merely from age.

### Step 5 — Build aggregation and listing services

Implement summary, series and execution-list reads in Postgres, with equivalent
small-data semantics in memory. Aggregate before pagination. Use one normalized
filter policy for every read. Avoid scanning all user chat payloads or fetching
all rows into the browser.

Calculate percentiles from selected raw observations. Sum repeated stage durations
per execution before calculating per-execution stage percentiles. Return stage
run coverage; do not replace unrun stages with zero samples. Preserve explicit
empty buckets and apply timezone/window boundaries consistently.

Use one deterministic fixture covering ten terminal eligible answer attempts:
six complete, one partial, one abstained, one system error, one cancelled. Expected
complete rate is 6/10, abstention 1/10, system error 1/10. Add separate in-flight,
tracker, malformed and artifact records and prove those do not alter these rates.
For eligible latency samples `[100,200,300,400,500]` ms, continuous P50 is 300,
P95 is 480 and P99 is 496. Use additional records for skipped verification,
multiple node attempts, unknown route and overlapping document groups.

Acceptance:

- [ ] Counts, denominators and percentile examples match exactly.
- [ ] Two pages of rows do not change total metrics.
- [ ] `[from,to)` boundaries and zero-volume buckets are tested.
- [ ] Unknown/expired/partial capture remains visible in results.
- [ ] Query plans for representative retained volume avoid whole-history Python scans.

### Step 6 — Expose additive, authorized analytics APIs

Implement milestone A endpoints from section 6. Apply Platform Admin auth at
each route/dependency boundary. Keep services transport-independent and adapters
out of routes. Use current HTTP schema/error conventions.

Add a focused public analytics OpenAPI contract test and register new HTTP handler
ownership with existing architecture tests where applicable. Existing ownership
tests may assert a fixed count; update the expected set/count consistently rather
than removing the assertion. Preserve the existing public query contract.

Acceptance:

- [ ] Platform Admin succeeds; System Admin, Space Admin, auditor, contributor and chat-member roles are denied according to current canonical account types.
- [ ] Detail lookup cannot bypass authorization by guessing an execution ID.
- [ ] Invalid time ranges, oversized windows, invalid enums and pagination limits rejected.
- [ ] API returns no query/answer text, SQL, secrets or raw exception strings.
- [ ] Existing query/session/evaluation endpoints remain unchanged.

### Step 7 — Add the Analytics route, contracts and Overview

Add `operational-analytics` to the registry and Platform Admin route set. Preserve
legacy `analytics -> evaluations`. Add lazy page composition in `App.tsx` and one
sidebar entry. Reuse an existing appropriate icon; a new icon system is unnecessary.

Build the page using existing layout, filters, React Query, typography and chart
patterns. Read the relevant frontend UI skill before implementation. Native SVG
and tables are sufficient for the initial line/stacked-bar charts; reuse existing
primitives where their responsibilities fit. Do not introduce a chart dependency
without a demonstrated unmet requirement.

Overview contents:

1. Filter bar: period, validated Knowledge Space scope, resolved source mode;
   additional filters can live in Queries until needed on Overview.
2. Cards: queries, complete-answer rate, abstention rate, system-error rate,
   P95 answer completion latency, verification coverage.
3. Query volume trend and outcome distribution over time.
4. P50/P95 latency trend and stage latency comparison with observation counts.
5. Resolved route/intent breakdowns and queries requiring review preview.
6. Links to owning ingestion, corpus, audit and resource pages.

Do not show incomplete evidence/quality charts with fake values. Display `No
recorded queries`, `Not measured`, `Details expired`, and `Could not refresh`
as separate states. Show stale data with its last successful refresh timestamp.

Acceptance:

- [ ] New navigation is visible only to Platform Admin; direct-link access is gated.
- [ ] `/analytics` still opens RAG Evaluation and `/evaluations` still works.
- [ ] Chart segment click opens Queries with the exact population/window filters.
- [ ] Every chart has a readable label, unit, summary and accessible data table.
- [ ] Keyboard access, visible focus, non-color status cues, reduced motion and narrow layouts work.
- [ ] No per-chart independent filter logic or fake production seed data.

### Step 8 — Add Queries and the metadata inspector

Build a server-paginated table with timestamp, short trace/execution ID, resolved
route/intent, outcome, duration, verification status and explicit review reasons.
Show actor identity only through an authorized safe projection. Initial cross-user
rows do not show query excerpts. Avoid N+1 actor/document fetches per table row.

Review reasons are an explainable union of known signals: partial answer,
operational failure, failed check, unsupported claims, and missing citation on a
citation-applicable answer. A correctly abstained request or conversational answer
must not be flagged merely because it has no citations. Add low score only with
a valid threshold as specified in section 4. Store/filter reason codes, not a
fabricated aggregate confidence percentage.

The inspector initially shows outcome/reason, route decisions, model/configuration
identity, repeated node timings, verification method/status/subject and available
summary evidence counts. Use a link or drawer/modal following existing accessible
patterns. Support loading a detail URL directly and returning to the filtered list.

Acceptance:

- [ ] Review counts match the list under the same filters.
- [ ] A detail link survives reload and back navigation restores filters/page.
- [ ] Empty, forbidden, deleted-history and expired-detail states are distinct.
- [ ] Own-session links retain current access checks; cross-user content stays restricted.
- [ ] Opening an inspector does not rerun the query or call a model.

### Step 9 — Retention, coverage and milestone A release

Implement an idempotent, bounded query-owned maintenance CLI for expiration and
safe abandoned-execution reconciliation. Compose it into a suitable established
maintenance mechanism only if its responsibility/lifecycle fits; do not place
query policy inside ingestion/artifact services. If no suitable scheduler exists,
document the operator scheduler invoking the CLI. Do not claim automatic retention
is active until an actual configured invocation is verified. No new process is
required merely to write this plan.

Expire detail independently of summary records. Current requests are never
deleted or marked interrupted based on an arbitrary short timeout. Tie
reconciliation to a real execution deadline plus grace and account for long
summaries. If liveness cannot be established, leave an explicit unresolved state.
Retention is a release requirement; do not ship indefinite accidental retention.

Do not silently backfill historical production analytics from chat history. It
excludes failures and may lack current fields. Initial history begins at deployment.
A future backfill must label imported records/coverage, exclude them from metrics
with missing denominators, and be idempotent by source turn identity.

Acceptance:

- [ ] Maintenance runs twice safely, uses bounded batches and exits nonzero on failure.
- [ ] Summary/detail expiration rules are independently tested.
- [ ] Effective retained window and capture limitations are visible in the UI/API.
- [ ] Baseline vs instrumented query overhead and analytics read performance measured.
- [ ] All milestone A checks in section 9 pass or unrelated baseline blockers are documented.
- [ ] Administrator/operator documentation describes access, metric meaning, retention and collection failures.

### Step 10 — Retain bounded production retrieval lineage

Extend the existing trace capture path rather than implementing a second retriever.
Record existing stages (`retrieved`, `rerank_input`, `reranked`, `post_policy`,
`final_evidence`), attempts and skipped status. Add actual sent-to-generation and
cited mappings at the owning synthesis/citation boundary where those are known.

Preserve stable generation-aware candidate identity and raw/adjusted score types.
For exhaustive summarization and parent promotion, distinguish candidate chunks,
coverage units, context blocks and final citation anchors. Do not invent a 1:1
mapping or a monotonically shrinking funnel when evidence is expanded/merged.

Set a validated per-execution diagnostic cap based on measured payload size;
return original counts and `truncated=true` when exceeded. Count required document
usage/summaries before truncation; if that is not implemented, mark those derived
metrics incomplete. Never retrieve unauthorized candidates to count access filtering.

Acceptance:

- [ ] Sync/SSE/retries/summary routes produce truthful stage status/counts.
- [ ] Duplicate candidates, promotions and generation changes preserve identity.
- [ ] Trace payload excludes text and unsafe exception fields.
- [ ] Absent/truncated/expired details do not masquerade as zero evidence.
- [ ] Normal query answers/order/authorization unchanged and capture overhead measured.

Implementation status: complete for the retained-lineage slice. `LocalRagService`
automatically enables the existing retrieval trace whenever analytics is active,
so synchronous, SSE, retry, tracker and evaluation executions use one capture
path. `RetrievalTraceCandidate` now includes `index_generation_id`; safe rows
exclude evidence text and reranker exception details. The analytics record stores
`retrieval_lineage_status` plus bounded JSONB lineage with original stage counts,
attempt/status, candidate identity, coverage-unit counts, synthesis source keys,
citation keys, summary counts, and explicit truncation. Candidate and payload caps
are configured by `QUERY_ANALYTICS_RETRIEVAL_LINEAGE_MAX_CANDIDATES` and
`QUERY_ANALYTICS_RETRIEVAL_LINEAGE_MAX_BYTES`. The detail endpoint exposes lineage;
list responses retain metadata only. A representative 76-candidate local trace
serialized in 0.293 ms per execution at 17.2 KB; this is a capture-cost baseline,
not a long-run production performance claim. Sync and SSE live checks returned all
five stages, while retry and summary behavior remain covered by the focused query
tests.

### Step 11 — Retrieval and Performance tabs

Add retrieval score distributions by score type/model; top reranker score
median/mean/P10; documents/query; actual stage funnel; evidence utilization; mean
absolute rank movement and top-k turnover. Keep added/dropped/unscored candidates
separate. Rank comparisons use the same execution attempt and candidate universe.

Performance adds stage P50/P95, repeated-stage time, first-token vs completed-answer
latency, and available prompt/context-size comparisons. Estimated token counts
must be labeled estimates and not mixed with actual provider usage.

Use recorded effective configuration/build identity for comparisons. A change
first observed in query records is labeled `Configuration first observed`, not
`Deployment completed`. Real deployment/config-change markers use the owning
feature's recorded event timestamp via its public contract. Missing provenance
means unavailable markers, not guessed deployment times.

Acceptance:

- [ ] Each distribution/percentile has count, eligible cohort and score/timing definition.
- [ ] No averaged percentiles or signed movement cancellation error.
- [ ] Stage drill-down preserves model/config/attempt selection.
- [ ] Parent/context/citation mismatches yield unavailable utilization, not invented percentages.
- [ ] Route/cohort changes remain distinguishable from model/deployment regressions.

Implementation status: the first Step 11 slice is complete. The query-owned
`/admin/query-analytics/diagnostics` endpoint aggregates retained stage candidate
counts, retrieval/rerank/adjusted-rerank score percentiles and pipeline node timing
percentiles with the same filters as Overview. The Analytics page now exposes
URL-persisted Overview, Queries, Retrieval and Performance tabs. Capture states
remain explicit, so old `not_captured` records and windows without timing data are
shown as unavailable instead of zero-valued evidence. The diagnostics now also
expose generation-aware documents/query, top retrieved documents, and rerank-input
to final-evidence top-k overlap with added/dropped counts. Each new execution now
stores a text-free effective model/configuration cohort snapshot, configuration and
image digests, and diagnostics group first-observed cohorts without labeling them
as deployment completion. Long-run production comparisons remain.

### Step 12 — Qualified answer and citation quality

Add automated faithfulness trend split by method/status, with verification
coverage and evaluated-answer subject. Do not relabel existing scores as complete
claim support. Start with existing evidence-window support states and distinguish
`verified` from `semantic_fallback`.

Implementation status: the first qualified quality slice is complete. The
diagnostics endpoint now returns verification status/method distributions,
checked-score percentiles, checked/applicable counts, and retained evidence-window
support states. The series endpoint returns a per-bucket mean checked score, and
the Analytics page exposes a URL-persisted Quality tab. Skipped and failed checks
are excluded from score aggregates. Analytics now reuses the final text-free claim
ledger to report supported, unsupported, unknown, cited, uncited, and valid-quote
counts with separate support and citation-coverage denominators. Repair metadata
keeps draft attempts separate from the final answer ledger.

Citation-verification fields remain optional for stored-response compatibility
and specialized evaluation or artifact workflows. Normal chat answers do not
populate a claim ledger. Analytics treat absent verification data as not captured
and do not infer complete claim coverage from evidence windows.

Retain text-free verdicts/IDs by default. Full rejected-draft or cross-user answer
content capture is a later governed review feature with its own access/retention
contract. Without retained authorized content, label an inspector as metadata-only
and do not claim the exact evaluated draft can be replayed.

Acceptance:

- [x] Skipped/failed checks excluded from score averages and shown separately.
- [x] Semantic fallback not counted automatically as verified support.
- [x] Uncited factual claims included in coverage denominator when ledger enabled.
- [x] Replacement answers cannot inherit a draft's citation/support claims.
- [x] Citation support and coverage are separate metrics with tested denominators.

### Step 13 — Ingestion and corpus analytics in their owners

Extend ingestion's authorized aggregate API with time-bucketed successes/failures,
normalized error categories and job turnaround. Count initial documents and retry
attempts separately. Created-to-completed duration is turnaround, not CPU time.
Active processing time requires explicit stage/attempt starts/ends and separate
queue/review waits. Do not reconstruct a status history from only current state.

Extend corpus summaries using generation-aware indexed chunk counts, token-length
histograms, existing normalized chunk hashes and quality flags. Prefer summaries
computed at ingestion/publication to a Qdrant-wide scan on each dashboard read.
Reingestion replaces the active-generation summary; retired generations must not
inflate current-corpus duplicate/chunk counts. Separate scanned/OCR from text-native
PDF where provenance supports the distinction; unknown remains unknown.

Join complete query/document observations to authorized current corpus metadata
through owner contracts for most retrieved/cited/explicitly selected documents,
source-type usage, document heatmaps and not-observed-in-window lists. Define
whether each chart counts executions, documents, chunks or citation occurrences.
Distinguish documents too new for the full window from older unobserved documents.

Acceptance:

- [ ] Jobs/attempts/documents and turnaround/processing durations are not conflated.
- [ ] Ingestion filters and aggregate access match existing list semantics.
- [ ] Duplicate hash counts exclude retired generations and distinguish duplicate text from duplicate files.
- [ ] No silent document cleanup or indexing changes based on usage statistics.
- [ ] All-time absence is not inferred from seven days of trace retention or sampled data.

### Step 14 — Security and group usage

Extend System Audit/query diagnostics with structured explicit denial categories
and selected-group/actor-clearance distributions. Use canonical access values
and server-side authorized aggregates. Default remains Platform Admin.

Zero retrieval results do not prove access denial. Do not issue an unfiltered
search to infer which restricted documents would have answered a query. A group
heatmap must state whether its axes use requested query scope or retrieved-document
ownership; group membership is not evidence that the user queried every group.
Shared documents and multi-group queries require distinct-count rules.

Acceptance:

- [ ] Only observed authorization decisions count as denials.
- [ ] Unknown/early-auth failures do not acquire invented users/groups/clearances.
- [ ] Revoked permissions and shared-document cases tested.
- [ ] Any later scoped-admin feature applies authorization before aggregation,
  filter-option enumeration and pagination, not only before displaying rows.

### Step 15 — Infrastructure history

Keep collection owned by deployment/resource capabilities. Existing readings are
host-visible snapshots, including whole-device NVIDIA counters where supported.
They are not per-query GPU utilization or per-container resource limits.

First retain bounded timestamped snapshots with explicit host/device identity and
missing values. Collection must continue without an admin browser open; browser
polling is not a historical collector. Select an existing operational metrics
stack if deployed; otherwise justify an independently scheduled collector before
adding a process. Define retention/sample interval and measure overhead.

Then add adapters for actual model-server TTFT/tokens/sec/KV cache, Qdrant search/
index counters, PostgreSQL pool/query observations and Redis memory/hit/latency
where available. Verify current official exporter/provider documentation when
implementing these adapters. Never install GPU libraries or grant Docker-socket
access just to draw charts. Do not record slow-query SQL containing user content.

Acceptance:

- [ ] Unsupported hardware/services show unavailable; missing samples are gaps.
- [ ] Host, device, remote inference and application scopes are labeled correctly.
- [ ] No duplicate scrape observations across API replicas.
- [ ] Collector outages and retention are visible and documented.

### Step 16 — Feedback and labeled rephrase signals

Add an owner-scoped answer feedback API and UI control: positive/negative rating,
allowlisted reason, actor, stable execution/turn ID and timestamp. Choose one
effective rating per actor/answer with idempotent updates and authorized deletion.
Browser mutations retain centralized CSRF. Do not add freeform feedback text until
its content/retention needs are addressed.

Show positive/negative trend plus **feedback participation rate**. Unrated answers
are neither positive nor negative. Review reasons reflect current effective rating;
avoid double-counting rating edits as extra respondents.

For behavioral feedback, first implement an explicitly labeled repeat-query
signal if useful. A same-session/time-window match is not a semantic rephrase
detector. Semantic similarity needs a separately evaluated method that respects
session ownership, data retention and optional inference cost. Distinguish an
ordinary follow-up/clarification from a likely rephrase. The proposed 30–120 second
window is a hypothesis, not proof of dissatisfaction.

Acceptance:

- [ ] Users can rate only their own authorized answer; duplicate/update requests are idempotent.
- [ ] CSRF, validation, deleted answers and revoked-session cases covered.
- [ ] Rating percentages include respondent counts and participation denominator.
- [ ] Repeat/rephrase charts name the actual detection method and limitations.

### Step 17 — Correlations and review-to-evaluation workflow

Add binned/scatter exploration for reranker score vs automated faithfulness or
feedback, context size vs latency, and evidence count vs automated faithfulness.
Require compatible score type/model, verification method, route, configuration
and time cohort. Show sample size and missing-value/feedback coverage; sparse
bins should not yield confident threshold recommendations.

These are associations, not causal evidence that changing top-k or a threshold
improves answers. Do not tune production automatically. Candidate policy changes
should be tested with controlled comparisons and reviewed representative examples.

Optionally let an authorized reviewer create a draft evaluation case from a
reviewed example using the evaluation owner's existing public contract. Expected
answer/evidence must be supplied or verified by the reviewer; do not convert the
system's own answer or verdict into ground truth automatically. Do not create
duplicate evaluation infrastructure under analytics.

Acceptance:

- [ ] Mixed model/score/method populations cannot silently form one threshold curve.
- [ ] Feedback selection bias and sample counts visible.
- [ ] No automatic RAG policy mutation.
- [ ] Any evaluation export preserves authorization/provenance and requires real expected evidence.

## 8. Coverage of the original 36 proposals

This table prevents roadmap items from disappearing when milestone A ships.

| # | Proposal | Step / qualification |
| --- | --- | --- |
| 1 | Query volume | 3–7; eligible attempts and users, not audit actors |
| 2 | Outcome breakdown | 1, 4–7; include partial/clarification/cancellation |
| 3 | Route distribution | 3, 5, 7; resolved route, actual graph/conversation paths |
| 4 | Intent analytics | 3, 5, 7; internal intent rather than only public categories |
| 5 | End-to-end latency | 4–7; label server boundary, add first-token timing |
| 6 | Pipeline breakdown | 3, 5, 7, 11; retry-aware and additive cohort rules |
| 7 | Stage trend/deployment markers | 11; actual event provenance |
| 8 | Score distributions | 10–11; raw dense/sparse separation needs extra retrieval instrumentation |
| 9 | Top evidence score | 10–11; model/stage-specific |
| 10 | Reranker movement | 10–11; absolute movement, entrants/exits |
| 11 | Documents per query | 10–11; distinct generation-aware identity |
| 12 | Evidence funnel | 10–11; actual stages, summary branches and retries |
| 13 | Evidence utilization | 10–11; actual supplied-to-cited mapping |
| 14 | Groundedness trend | 12; automated faithfulness with method/coverage |
| 15 | Supported/unsupported claims | 12; complete claim ledger required |
| 16 | Citation analytics | 10–12; presence, coverage and support separate |
| 17 | Abstention trend | 3–7; normalized observed reasons |
| 18 | Queries requiring review | 8, 12, 16; explainable reasons, no wrong-answer label |
| 19 | User feedback | 16; new persistence and UI |
| 20 | Rephrased query rate | 16; detection method must be implemented/validated |
| 21 | Most queried documents | 13; explicit selection, not retrieval frequency |
| 22 | Most retrieved documents | 10, 13; complete document observations |
| 23 | Rarely/never retrieved | 13; eligible corpus and covered window |
| 24 | Document retrieval heatmap | 13; same counted unit and access scope |
| 25 | Knowledge source usage | 13; executed source type, not just corpus file mix |
| 26 | Ingestion trend | 13; documents vs jobs/attempts |
| 27 | Ingestion failure reasons | 13; safe categorized codes |
| 28 | Processing time | 13; turnaround initially, explicit active timing later |
| 29 | Chunk-size distribution | 13; tokenization definition and stored generation summaries |
| 30 | Chunks/document | 13; comparable size/page units and current generation |
| 31 | Duplicate/low-information chunks | 13; existing hashes/flags plus defined heuristics |
| 32 | Security access | 4, 14; explicit denials only |
| 33 | Group usage heatmap | 14; selected scope vs evidence ownership |
| 34 | Infrastructure | 15; service collectors and retention beyond current snapshots |
| 35 | Correlations | 17; compatible cohorts, no causal claim |
| 36 | Reranker vs feedback | 16–17; feedback coverage and model-specific bins |

## 9. Validation and release checklist

Use existing pytest/Vitest setups. Add focused behavior tests, not a parallel
test framework. Test the real SQL adapter against a disposable configured test
database for bootstrap/concurrency/filter/percentile behavior; a memory-only test
cannot prove PostgreSQL semantics. Never run destructive tests on production data.

### Required test locations

| Area | Coverage |
| --- | --- |
| `backend/tests/query/analytics/` | Lifecycle, metrics, repositories, routes, privacy, maintenance |
| Existing query service/stream tests | Success/failure/cancellation/history compatibility; no extra query/model work |
| `backend/tests/architecture/test_public_query_analytics_api_contract.py` (new) | Additive OpenAPI shapes, permissions and expected paths |
| Existing architecture ownership tests | Query ownership, route-to-service boundaries, no new cross-feature internals |
| `frontend/src/features/analytics/**/*.test.ts(x)` | Filters, metrics labels, table/inspector states and navigation |
| `frontend/src/lib/api/contracts.analytics.test.ts` (new) | GET method, path, encoded IDs, filters, errors and response normalization |
| `frontend/src/routes/routes.test.ts` and sidebar tests | New route gating, legacy aliases, existing navigation unchanged |
| Later owning capability tests | Ingestion jobs/workers, document access/generations, feedback CSRF, resource adapters as changed |

Run focused checks after each slice, then broader gates at milestones. Commands
below are from repository root; use Node 22/npm 10. Do not reinstall dependencies
unless necessary. Do not mark a command passed if it was not run.

```bash
uv run --directory backend --locked --extra dev python -m pytest tests/query/analytics
uv run --directory backend --locked --extra dev python -m pytest tests/query
uv run --directory backend --locked --extra dev python -m pytest tests/architecture
uv run --directory backend --locked --extra dev ruff check apps src tests
npm --prefix frontend test -- src/features/analytics src/routes/routes.test.ts src/lib/api/contracts.analytics.test.ts
npm --prefix frontend run typecheck
```

Before releasing milestone A/B:

```bash
uv run --directory backend --locked --extra dev python -m pytest tests
npm --prefix frontend test
npm --prefix frontend run build
npm --prefix frontend run check:dead-code
scripts/check_dead_code.sh
docker compose config --quiet
```

Configuration changes additionally run the existing configuration contract test.
Dependency/image changes additionally check the affected lock, build the affected
image and run an import/health smoke test. Worker changes require owning execution,
adapter and task-registration tests. This plan does not itself require those
changes or authorize skipping their checks when they become necessary.

### Manual acceptance script

Use a disposable/local workspace with known permissions and controlled examples:

Use the corpus-derived cases in [query-cases.md](query-cases.md) for the
document-backed scenarios below. Refresh the document IDs when the local corpus
changes.

1. Record a complete answer, partial answer, clarification and abstention.
2. Exercise a known service failure and a cancelled streaming answer.
3. Deny a valid authenticated request by group/source access; send an invalid
   request separately. Check their different populations and status handling.
4. Run the live Query Tracker and an evaluation case. Neither increases the
   default production answer count.
5. Retry an internal retrieval, then separately resubmit a query. Confirm one
   execution with repeated stages vs a distinct new execution attempt.
6. Open Analytics, filter a window/group/outcome, click a chart, open its query
   inspector, reload, and navigate back. Counts and filters remain consistent.
7. Verify no-data, skipped-check, failed-check, missing-source and expired-detail
   states. Revoke document access and confirm preview content is no longer returned.
8. Restart an API replica and verify retained records. Exercise concurrent writes
   through both replicas without duplicates from one execution's lifecycle hooks.
9. Make telemetry storage unavailable in a controlled test. Original query outcome
   remains correct and capture failure is observable; no false complete-coverage claim.
10. Run retention twice on disposable records. Verify detail expiry, summary
    retention, current execution protection and safe maintenance failure reporting.
11. Check keyboard-only chart/table navigation, inspector focus return, screen
    reader labels, reduced motion and narrow viewport layout.
12. Compare baseline and instrumented execution duration with inference stubbed
    and with representative normal/summary workloads. Record storage bytes per
    execution and aggregate API p50/p95 on a stated dataset size; use measurements
    to set a release budget rather than asserting an unmeasured performance target.

### Release and rollback

- Add schema before code begins writing it; additive tables preserve old query code.
- Validate collection and retention in a controlled workspace before enabling the
  user-facing page. Never populate production charts with illustrative fake data.
- Roll back application collection/routes using the prior compatible application
  version if necessary; do not drop collected tables or user history as rollback.
- Document the earliest reliable capture timestamp, retention schedule, scope,
  unsupported metrics and any known gaps. Historical data is not retroactively
  complete merely because the page now exists.
- Update manual source Markdown under `docs/manuals/` when behavior ships. If
  generated manuals are updated, use `scripts/build_user_manuals.py`; do not edit
  generated files by hand.

## 10. Luna's implementation log

Update this section at the end of each completed slice. Keep future steps unchecked.
No new Codex task is created by this document; implementation can run in whichever
task the user chooses.

| Step | Status | Files changed / evidence | Tests run and results | Remaining limitations |
| --- | --- | --- | --- | --- |
| 0 | Complete | Repository baseline was reviewed before the analytics slice; unrelated worktree changes remain untouched. | Backend query and architecture suites completed; frontend typecheck, test suite, and build completed. | Existing worktree has unrelated modifications that remain outside this slice. |
| 1–9 / A | In progress | Added query-owned execution records, idempotent memory/Postgres repositories, lifecycle capture for chat/tracker/evaluation paths, bounded retention/reconciliation via `rag.ops.query_analytics_maintenance`, query boundary-event capture, Platform Admin summary/list/series endpoints, and `/operational-analytics` UI with URL-persisted filters, review signals, zero-filled volume/outcome/latency charts, clickable bucket drill-down, and metadata inspector. | Analytics backend tests — 9 passed; full query suite — 672 passed; architecture suite — 57 passed; analytics lint and Docker Compose validation pass; frontend suite — 292 passed; frontend typecheck and production build pass. Repository dead-code check reaches the existing unrelated unused-export findings. | Full manual acceptance remains. Remaining quality, ingestion/corpus, security, infrastructure, and feedback analytics remain in Milestones B–D. |
| 10 / B | Complete | Reused the query retrieval trace; added generation-aware IDs, text-free bounded JSONB lineage, synthesis/citation mappings, explicit status/truncation, and detail-only API exposure. | 43 focused backend tests passed; analytics/architecture lint passed; frontend typecheck passed; live sync and SSE admin queries returned all five stage names, no text or reranker exception fields, and available generation/citation mappings; representative 76-candidate lineage serialization measured at 0.293 ms and 17.2 KB. | The benchmark is local and representative; collect long-run production overhead after real traffic exists. |
| 11 / B | Complete for the analytics slice | Added filtered `/admin/query-analytics/diagnostics` aggregation for retained stage scores, rank movement, evidence utilization, safe node timings, generation-aware documents/query, top retrieved documents, rerank-input to final-evidence top-k overlap, and first-observed model/configuration cohorts; Retrieval and Performance include the diagnostic tables. | Analytics tests — 13 passed; analytics/architecture lint passed; frontend analytics API tests — 4 passed; frontend typecheck/build passed; live Postgres diagnostics returned document observations and top-k comparisons; rebuilt API/query-api/frontend containers are healthy; authenticated 24-hour and 30-day windows both returned 21 terminal executions and one observed cohort. | Long-run production comparisons and deployment-owner event provenance remain. |
| 12 / B | Complete | Added qualified quality diagnostics for verification status/method, checked faithfulness score distributions, verification coverage, verified versus semantic-fallback evidence-window states, and final text-free claim-ledger counts with separate support/citation coverage denominators; added per-bucket checked-score trend and a URL-persisted Quality tab. Selectively reingested the NIST and Takaful corpus documents through the supported lifecycle route, rebuilt/restarted the ingestion worker, and verified active Qdrant generations carry `content_hash`, `evidence_hash`, `provenance_kind`, and publication state. Fixed configured-cloud citation JSON compatibility, exact verdict prompting, native quote validation, omitted-citation recovery, and multi-need evidence subquery coverage. | Focused backend validation — 156 tests passed; Ruff passed; the normal API image rebuilt successfully; live authenticated A-01 and A-02 both returned HTTP 200, `complete`, `faithfulness_status=checked`, verified citations, available text-free retrieval lineage, and no degradation. API/query-api/frontend containers are healthy after recreation from the rebuilt image. | Production rollout promotion and long-run overhead measurement remain. |
| 13–15 / C | Not started | — | — | Owner-specific operational additions |
| 16–17 / D | Not started | — | — | Feedback and compatible-cohort data needed |

Suggested handoff instruction:

> Start from the latest review-fix record below. Deploy and verify the corrected
> A/B slice before claiming release acceptance. Preserve unrelated changes and the
> legacy `/analytics` evaluation alias. Keep future milestones unchecked and
> cross-user content restricted; do not invent unavailable metrics.

### Review fixes — 2026-09-09

This record supersedes earlier completion claims for the affected behavior.
Historical implementation entries above remain as evidence of their earlier runs.

| Finding | Implemented correction | Verification |
| --- | --- | --- |
| Repeated requests on every render | A stored UTC snapshot drives stable request keys. Only the visible view fetches; automatic refresh runs every 30 seconds while visible and pauses during paging/inspection. | State tests and browser request-count checks; page two stayed fixed across 65 seconds. |
| Document titles leaked through lineage and aggregates | Capture and historical detail use an explicit candidate allowlist. Document titles are omitted from both repositories' aggregate output and the HTTP mapper. | Memory/PostgreSQL tests seed historical private fields and check detail and diagnostics responses. |
| Analytics construction could fail a query | Repository construction performs no DDL; bootstrap owns schema changes. Query-service initialization and analytics serialization/write failures preserve query behavior and emit safe warnings. | Query-service construction and recorder failure regressions. |
| Detail did not expire independently; no scheduler | Bounded cleanup expires evidence after seven days while preserving timing data for the summary lifetime. Compose includes a healthchecked `query-analytics-maintenance` process using the API image. | Memory/PostgreSQL repeated-cycle tests, active-row protection, success-only heartbeat test and Compose/architecture validation. The deployed service completed a scheduled cycle, passed its healthcheck and accepted a second manual cycle. |
| Evaluations/artifacts contaminated the default population | Both HTTP defaults and UI use `origin=chat`, `work_kind=answer`; explicit selectors support other populations or `all`. | API regressions and frontend state/contract tests. |
| Eligible permission denials were absent from query outcomes | Shared sync/SSE/tracker authorization records a metadata-only `access_denied` execution with a server ID and reason code. Middleware avoids a second boundary event. | Permission-route and duplicate-boundary tests; existing CSRF/authentication behavior preserved. |
| Retry attempts distorted stage percentiles | Sum repeated stage durations within each execution before computing P50/P95. Report execution count and individual timing sample count separately. | Both repositories: samples 100+200 ms versus 500 ms produce P50 400 ms and P95 490 ms. |
| Only the first 50 executions could be inspected | Added pagination, an independent detail request, retained lineage/timing presentation, distinct error/expiry states, and URL state for bucket, page and selection. Insertion timestamps exclude late inserts from the selected snapshot. | API/state/inspector tests; browser reload, Back, bucket drill-down, keyboard use and 320/390-pixel layout checks. |
| PostgreSQL lost the requested source mode | Persist `requested_source_mode` in the initial INSERT, including for failed executions; retries preserve the original record. | Memory/PostgreSQL idempotency and failure regression. |

Related checks also fixed UTC timestamps, nullable score rendering and chart
buttons hidden from assistive technology. Reconciliation skips locked/terminal
rows. At this review-fix deployment, scheduled cleanup left unresolved in-flight rows alone:
existing stored deadlines are start time plus grace, not an enforced workflow
deadline. Automatic interruption requires trustworthy deadline or liveness data;
an old request must not be declared dead merely because it is old.

Validation for this fix set:

- Query, architecture and evaluation suites: 882 passed, 10 skipped. Seven skips
  are the opt-in PostgreSQL cases, which passed separately; three depend on other
  external integrations.
- Disposable PostgreSQL plus memory regression run: 15 passed. Each PostgreSQL
  case uses its own schema and applies bootstrap twice; application data is untouched.
- Frontend suite: 309 passed; typecheck and production build passed. Browser checks
  use synthetic API responses with the real page and components, not live model
  queries. The only browser console errors were the fixture's missing favicon.
- Focused Ruff and Docker Compose configuration validation passed.

### Local deployment verification — 2026-09-09

The registry retry succeeded. Both images were built through their normal
Dockerfiles with locked dependencies. API, query-api, frontend and the new
query-analytics-maintenance service were recreated and passed Compose health
checks. Other services and data volumes were not recreated.

| Image | Deployed image ID |
| --- | --- |
| API and analytics maintenance | `sha256:71bbb19f8d417d919b91ae612e8d13352c05434e0eb1a532661ec05b2d9502bc` |
| Frontend | `sha256:a9869af7652c1a6d84d4659a428f13a89512910f9edc137732a16ac754ab0569` |

Live verification through the frontend proxy:

- Analytics page, summary, list, series, diagnostics and historical detail returned
  HTTP 200. Default population contained 54 chat-answer executions versus 56 for
  all origins/work kinds before the smoke queries; page two preserved `as_of`.
  Lists omitted lineage and diagnostic responses omitted document titles.
- The existing `/notest` member received HTTP 403 for both sync and SSE `/test`
  queries. Exactly two eligible `access_denied` records retained
  `reason_code=query_group_forbidden` and `requested_source_mode=corpus_only`.
  The member could not access admin analytics.
- NIST A-01 returned HTTP 200, `complete`, verification `checked`, available
  lineage with five stages and 14 timing samples. Execution:
  `0a088e15-2716-4107-8acc-ffc86d501567`. Evidence metadata contained no title/text
  fields. Smoke-test login sessions were logged out afterward.
- Analytics maintenance completed its first scheduled cycle, passed its explicit
  healthcheck, and completed a second bounded CLI cycle. Both found zero records
  due for expiration; actual expiry behavior was covered by the disposable
  PostgreSQL regressions. Automatic retention is now active on the local stack.

Rollback images remain tagged
`agenticrag-api:before-analytics-review-20260909` and
`agenticrag-frontend:before-analytics-review-20260909`. The pre-existing unhealthy
artifact-maintenance service is outside this analytics deployment.

Remaining broader release work: production overhead and retained-window/capture-gap
visibility. Abandoned-query detection is addressed by the follow-up below. The UI currently offers
24-hour, seven-day and 30-day presets; a custom range input and authorized
document-content previews remain outside this fix set. Analytics continues to
expose metadata only. C/D are not part of this deployment.

No historical backfill, model calls, new package dependencies, routing-threshold
changes or C/D placeholder features were added by these review fixes.

### Abandoned-query detection follow-up — 2026-09-09

Implemented heartbeat tracking in the shared query service for synchronous,
streaming, Query Tracker, evaluation and artifact-submission execution. A heartbeat
runs independently of blocking model/retrieval work and stops when the execution
scope exits. It uses the existing repository, background cleanup process and
`QUERY_ANALYTICS_RECONCILIATION_GRACE_SECONDS` setting, with no new package or
process. The follow-up is deployed and verified below.

- New records have `last_heartbeat_at` and a renewed reconciliation deadline.
  A partial index supports bounded reconciliation; idempotent bootstrap adds the
  nullable heartbeat field without inventing data for older executions.
- Heartbeats run every 30 seconds, or one third of the grace period if shorter.
  The default grace remains 3600 seconds after the last successful heartbeat.
  There is no total duration limit for a healthy query. Cleanup normally detects
  a missing heartbeat within 60–65 minutes, plus backlog, at default settings.
- Cleanup marks only expired, heartbeat-tracked rows `interrupted`, with safe
  reason `analytics_heartbeat_expired`. The dashboard says **Heartbeat overdue**
  and explains that interruption is inferred; no query is cancelled by analytics.
- A returning heartbeat restores an inferred interruption to in-flight. A real
  final result supersedes that inference; ordinary completed, failed or cancelled
  results remain immutable. Row locking protects concurrent renewal/completion
  and cleanup. Inferred interruptions get 30 days from reconciliation before
  summary deletion, preserving a window for late results.
- Old executions without heartbeat tracking display **Status unknown** and remain
  outside automatic reconciliation. A heartbeat gap cannot distinguish a process
  crash from a database/network outage with certainty; the qualified status and
  correction behavior make that limitation explicit.

Validation: query/architecture/evaluation suites **898 passed, 14 skipped**;
disposable PostgreSQL/memory regressions **20 passed, one memory-only skip**;
frontend **316 passed**, typecheck/build passed, focused Ruff and Compose checks
passed. Tests cover long-running requests, missed heartbeats, recovery, immutable
terminal outcomes, legacy records, sync/SSE/tracker/artifact cleanup, cancellation,
storage failures and an actual SIGKILL of an isolated test process. The crash test
advances the maintenance clock past the persisted deadline after killing that
process; it does not kill an application service or wait an hour.

Deployment: rebuilt through the normal Dockerfiles and recreated API, query-api,
frontend, query-analytics-maintenance and the idle evaluation worker. All five
services passed healthchecks; the scheduled reconciler completed its first cycle.
The API/shared-worker image is
`sha256:fc23d33b2bc923217e2f6e544546639171d7b5f21fd56bfd97c683bc6bb6c634`;
the frontend image is
`sha256:0849335c9e5f6c5156a1b33c55a7fc8d0dc0570f58e5974a11936ce3c820aeb7`.
Rollback images were retained with `before-query-heartbeats-20260909` tags.

Live NIST A-01 execution `31bcd083-910b-4eff-b790-bf9d18238da7` returned HTTP 200,
`complete`, verification `checked`, a persisted heartbeat and
`liveness_status=finished`. The analytics list exposed both new liveness fields;
older entries retained null heartbeat metadata. The smoke session was logged out
and the disposable PostgreSQL test container was removed.

### Browser review fixes — 2026-09-09

- Analytics now uses a column-chart sidebar icon; RAG Evaluation retains its
  activity icon.
- All trend charts display numeric Y ticks, the metric unit, UTC date ticks, and
  an X-axis title. Hourly buckets also show the time. HTML axis labels retain
  readable text sizes as the SVG plot resizes; exact values remain available in
  the accessible data table.
- Each chart's Filters button opens working period/outcome controls, synchronized
  with the dashboard toolbar and URL. The controls explicitly apply to all
  analytics charts and the query list. Escape collapses the controls and restores
  button focus; keyboard bucket drill-down and browser Back remain functional.

Validation: frontend **318 tests passed across 72 files**; typecheck, local
production build and frontend image build passed. Authenticated browser checks
against live data verified filter requests, shared filter state, URL changes,
keyboard collapse/focus and bucket drill-down. Checked chart layout at 320, 768,
1024 and 1440px, plus light and dark themes. The deployed frontend is healthy
with image `sha256:db5ce9fafde1774d27a2687d5303baf3bda257f292a552899bb7ad22ac05b114`;
the prior image is retained as `agenticrag-frontend:before-analytics-ui-20260909`.
This update changes only the frontend deployment.

## 11. References

- [Repository instructions](../../../AGENTS.md)
- [Product principles](../../../PRODUCT.md)
- [Repository README](../../../README.md)
- [Backend architecture](../../../backend/README.md)
- [Ingestion ownership](../../../backend/src/rag/ingestion/README.md)
- [Deployment/resource scope](../../../backend/src/rag/deployment/README.md)
- [Manual source guide](../../manuals/README.md)
- [Prometheus: histograms and summaries](https://prometheus.io/docs/practices/histograms/) — why precomputed percentiles cannot simply be averaged/aggregated.
- [Ragas: faithfulness definition](https://docs.ragas.io/en/v0.2.4/concepts/metrics/available_metrics/faithfulness/) — support against provided evidence is a distinct measurement from absolute answer correctness; this repository does not automatically implement the same metric.
