# Milestone A query cases

These cases are generated from the local QA corpus used by the September 8,
2026 query smoke run. They exercise analytics behavior and routing signals; an
expected outcome is a workflow expectation, not a claim that the generated
answer is absolutely correct.

## Corpus records

Both records were observed in Knowledge Space `/test` with clearance
`NATO_RESTRICTED`:

| Alias | Document ID | Title | Known content |
| --- | --- | --- | --- |
| `nist` | `ca036f42-22bf-4cf1-9c7a-1e778bcf4f44` | `NIST.AI.100-1.pdf` | AI RMF purpose, trustworthiness characteristics, four functions, and lifecycle guidance |
| `takaful` | `e2b584c6-0afb-4997-b7a-79ecbcf146cd` | `demo_insurance_policy.pdf` | Coverage, exclusions, claims documents, processing time, and contribution rules |

Use `source_mode=corpus_only` and the document IDs shown above for scoped
cases. Run the access case with a user who cannot read `/test`.

## Cases

| ID | Category | Query | Scope | Expected analytics outcome |
| --- | --- | --- | --- | --- |
| `A-01` | Direct lookup | What are the four core functions of the NIST AI Risk Management Framework? | `nist` | `complete`; citations should resolve to NIST evidence |
| `A-02` | Direct lookup | According to the Islamic Family Takaful Insurance Policy (Demo), what documents are required for a claim and how long does processing take? | `takaful` | `complete`; citations should resolve to the claims-process evidence |
| `A-03` | Focused explanation | What trustworthy AI characteristics does the NIST AI Risk Management Framework identify? | `nist` | `complete` or `partial`; inspect evidence count, verification status, and citations |
| `A-04` | Whole-document summary | Summarize the entire NIST AI Risk Management Framework document, covering its purpose, trustworthy AI characteristics, core functions, and implementation guidance. | `nist` | `partial` is acceptable when coverage is incomplete; it must be marked degraded and must not claim full coverage |
| `A-05` | Section retrieval diagnostic | Summarize section 2 of the NIST AI Risk Management Framework. | `nist` | `partial` or `abstained` if section evidence is not sufficiently identified; no fabricated section summary |
| `A-06` | No evidence | What is the 2026 retention schedule for the Prudentia production database? | `/test`, no document scope | `abstained` or an explicit no-evidence response; no invented policy or citation |
| `A-07` | Multi-document comparison | What is the main subject of each available document, and which document describes an AI risk-management lifecycle versus a claims process? | `nist` + `takaful` | `complete` or `partial`; both documents should appear in the evidence lineage if used |
| `A-08` | Authorization denial | What are the four core functions of the NIST AI Risk Management Framework? | `nist`, run as a user without `/test` access | HTTP `403`; one eligible execution with outcome `access_denied` and a safe reason code; no duplicate boundary event or answer content |
| `A-09` | Validation boundary | Submit an empty query or a malformed query payload to the query endpoint. | None | HTTP `422`; boundary event reason should be `validation_error`; it must not increase eligible query answer counts |
| `A-10` | Cancellation | Start a streaming whole-document NIST summary, then cancel the request after retrieval begins. | `nist` | `cancelled` or reconciled `interrupted`; the row must not remain indefinitely `in_flight` |
| `A-11` | Tracker origin | Run a small tracker case using the A-01 question and the NIST document. | `nist` | An execution with origin `query_tracker`; it must remain distinguishable from the default chat answer population |
| `A-12` | Evaluation origin | Import or select a case using the A-02 question and run it through the evaluation workflow. | `takaful` | An execution with origin `evaluation`; it must not inflate the default production chat answer count |

## Acceptance procedure

For every case, record the execution ID, HTTP status, outcome, degraded flag,
latency, verification status, citation count, and selected route in the
Analytics page. For A-01 through A-07, use the row inspector and confirm that
only operational metadata is shown.

After A-08 through A-10, verify the corresponding boundary or lifecycle rows:

- A-08 has one eligible query execution with outcome `access_denied`, without a generated answer.
- A-09 has a validation boundary event and no eligible answer.
- A-10 reaches a terminal cancellation or interruption state through the query
  lifecycle. For an abrupt process crash, a tracked execution becomes an explicitly
  inferred interruption after its last heartbeat deadline and a cleanup cycle.
  Older rows without heartbeat tracking remain unknown; age alone is insufficient.

Finally, filter Analytics by `origin`, `outcome`, route, and the `/test` space;
select a chart bucket; reload the page; and confirm that URL filters, counts,
and the execution list remain consistent.

## Known observations from the source smoke run

- A-01 returned a complete, source-supported answer in about four seconds.
- A-02 returned a complete answer with the claim requirements and 7–14 working
  day processing time.
- A-04 returned a partial, degraded summary because preparation covered only
  part of the 45 summary units.
- A-05 returned a partial response without a supported section summary. Keep
  this as a diagnostic case until section-heading retrieval is improved.

Refresh the document IDs and observations when the local corpus is replaced.

## Run results — 2026-09-08

These results came from the rebuilt `api` and `query-api` containers using the
Platform Admin account:

| Case | Result | Observed details |
| --- | --- | --- |
| `A-01` | Pass | `complete`, checked faithfulness, 2 sources, 13 citation targets, 4.2 s |
| `A-02` | Pass | `complete`, checked faithfulness, 1 source, 2 citation targets, 9.6 s |
| `A-03` | Pass | `complete`, checked faithfulness, 2 sources, 27 citation targets, 8.1 s |
| `A-04` | Expected partial | `partial`, `degraded=true`, reason `summary_coverage_partial`, 20 sources, 124 citation targets, 244.4 s |
| `A-05` | Pass with changed behavior | `complete`, checked faithfulness, 2 sources, 26 citation targets, 16.8 s; the earlier smoke run had returned partial |
| `A-06` | Pass | `abstained`, `degraded=true`, reason `insufficient_semantic_evidence`, 0 sources, faithfulness skipped, 4.0 s |
| `A-07` | Expected partial | `partial`, `degraded=true`, reason `exhaustive_final_evidence_coverage_partial`, 4 sources, 49 citation targets, 23.7 s |
| `A-08` | Pass | `notester@prudentia.ai` has `/notest` access; explicit `/test` query returned HTTP `403` with `query_group_forbidden`, and the boundary event was persisted |
| `A-09` | Pass | HTTP `422`; two `validation_error:422` boundary events persisted |
| `A-10` | Pass | Corrected probe canceled after the `abac_retriever` trace; analytics reached terminal `interrupted` in 3.6 s |
| `A-11` | Pass | Query Tracker streamed 53 events and recorded a `complete` execution with `origin=query_tracker` |
| `A-12` | Pass | One-case evaluation run `e1592dcc-85b6-43c2-bb2b-4f1fe8ce05cc` completed and recorded a separate `partial` execution with `origin=evaluation` |

Analytics summary and execution-list reads succeeded after fixing Postgres UUID
deserialization. The list showed the expected complete, partial, and abstained
outcomes plus review signals for degraded executions.

## Release validation run — 2026-09-09

The NIST and Takaful documents were selectively reingested through the supported
document lifecycle endpoint after the ingestion worker was rebuilt and restarted.
The active Qdrant generations now expose `content_hash`, `evidence_hash`,
`provenance_kind=native`, `index_generation_id`, and `generation_published=true`.

The configured provider also required two compatibility fixes: cloud faithfulness
requests use generic JSON mode with an exact verdict prompt, and native source
excerpts can validate quotes even when bounded quote windows are narrower. The
synthesis path now applies its existing safe citation insertion helper when a
model omits labels, while preserving mixed abstention responses. Explicit
multi-need evidence plans retain their generated subqueries even when the
additional query-planner stage is disabled.

Final authenticated smoke results:

| Case | Result | Observed details |
| --- | --- | --- |
| `A-01` | Pass | HTTP 200; `complete`; `faithfulness_status=checked`; citation status `verified`; 2 sources; lineage `available`; no degradation |
| `A-02` | Pass | HTTP 200; `complete`; `faithfulness_status=checked`; citation status `verified`; 1 source; lineage `available`; required and covered evidence slots both complete; no degradation |

Both executions recorded text-free retrieval lineage with generation-aware
candidate identity. The normal API image rebuilt successfully, both API replicas
were recreated from it, and the final smoke passed with all application
containers healthy.
