# Production RAG Hardening Checklist

Last reviewed: 2026-08-30

This checklist tracks the production fixes for source routing, database execution,
evidence completeness, and document-quality behavior. A checked item must have a
runnable regression test or an explicitly verified runtime change.

## Runtime and operations

- [x] Use `nemotron-3-super:cloud` as the fast SQL-generation model.
- [x] Use `gpt-oss:120b-cloud` only as the stronger reasoning/SQL repair model.
- [x] Allow prompt-only JSON for cloud models while retaining application-side validation.
- [x] Change Evidence Gate from `never` to `adaptive`.
- [x] Change Faithfulness from `never` to `adaptive`.
- [x] Confirm `connector-demo-db` is reachable before leaving its catalog approved.
- [x] Make query GraphRAG disabled when graph enrichment is disabled for the deployment.

## Authoritative evidence planning

- [x] Preserve a unique deterministic DB candidate when capability planning fails.
- [x] Ask for clarification when multiple DB candidates remain equally plausible.
- [x] Prevent a required DB assignment from being rewritten to corpus-only.
- [x] Add an Auto-mode regression using arbitrary client schema terminology.
- [x] Add an exact connector-name regression without generic DB keywords.

## Routing metadata

- [x] Generate an admin-reviewable routing profile during catalog enrichment.
- [x] Include catalog description, entities, table/column synonyms, metrics,
  example questions, exclusions, provenance, and freshness.
- [x] Backfill both existing approved catalogs.
- [x] Keep routing cards in memory while the authorized catalog set is bounded.
- [ ] Add a schema-routing index only after the candidate limit is measurably exceeded.

## Multiple database connectors

- [x] Materialize up to three connector assignments from an evidence plan.
- [x] Execute assigned connectors concurrently with bounded request-local fan-out.
- [x] Preserve connector and catalog lineage on returned rows.
- [x] Add backward-compatible `query_source_ids` or explicit `all_visible` request scope.
- [x] Return successful optional branches when another connector fails.
- [x] Mark the response degraded when a required connector fails.

## Coverage and operational failures

- [x] Track coverage by `(need_id, source_id, capability)` instead of only `need_id`.
- [x] Mark document-success plus required-DB-failure as partial and degraded.
- [x] Abstain with an operational error when an explicitly selected DB fails.
- [x] Return typed failures with stage, stable code, retryability, source ID, and
  safe operator message.
- [x] Show a specific safe UI message instead of “no accessible sources” for DB failures.

## Exhaustive document answers

- [x] Expand exhaustive retrieval through table and section boundaries.
- [x] Exclude standalone printed page numbers from embedded content.
- [x] Reject a claimed list count that does not match the enumerated items.
- [x] Run the Samsung repair-manual question as an end-to-end regression.
- [x] Require assignment and section coverage before returning `complete`.

## Required regression suite

- [x] Auto DB routing with arbitrary schema terminology.
- [x] Exact connector-name routing without DB keywords.
- [x] Malformed planner output preserves a unique deterministic DB assignment.
- [x] Inaccessible SQL model returns a typed operational error.
- [x] Hybrid response is partial when required DB evidence fails.
- [x] Two-connector fan-out preserves lineage and reports partial failure.
- [x] Disabled GraphRAG never appears in effective capabilities.
- [x] Samsung claimed count matches the enumerated list.
