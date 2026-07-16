# Local baseline — 2026-07-14

This is the first end-to-end baseline captured after building and importing the
`RAG test documents v1` benchmark. It records observed behavior; it does not
change retrieval, reranking, ingestion, worker, or model configuration.

## Corpus and dataset

- Source-folder inventory: 75 files.
- Clean ingestion manifest: 42 files, including 11 generated JSON derivatives
  for supported ingestion of useful XLSX, TXT, and DOCX evidence.
- Explicitly excluded source files: 44 (duplicates, question/answer leakage,
  unsupported or empty files, temporary files, and negative/stress fixtures).
- Evaluation cases: 84.
- Imported dataset ID: `f6b3f1db-b858-4f35-82cd-22b261664e13`.
- Core corpus: 19/19 complete and indexed.
- Answer-required documents: 18/18 complete and indexed at the manifest hash.

The final 42-file extended-manifest outcome was 27 complete/indexed, 9 in
human review, and 6 failed, with no jobs left queued or processing. The six
large-PDF failures exhausted three attempts after worker `SIGKILL` events:

- `9789240029200-eng.pdf`
- `Amazon-2025-Annual-Report.pdf`
- `artemis_plan-20200921.pdf`
- `Dell PowerEdge R630 Technical Manual.pdf`
- `ISO_IEC 27001_2022.pdf`
- `zero_trust_maturity_model_v2_508.pdf`

These are distractor/coverage files; none is required by an evaluation case.

## Smoke results

The four smoke cases were also run separately because the initial four-case
batch lost its evaluation worker to `SIGKILL` after the first case. The
redelivered task saw the run in `running` state and returned without resuming;
the orphaned run was cancelled after its stale heartbeat was confirmed.

| Case | Result | Primary observation |
| --- | --- | --- |
| `fir-026` | Pass | Retrieved and cited all five FIR investigating officers. |
| `samsung-equipment-001` | Fail | Correct document was indexed, but retrieval omitted pages 51–53 and the answer omitted 10 required items. |
| `insurance-010` | Fail | Retrieved unrelated document content instead of the two indexed insurance sources. |
| `structured-003` | Fail | Retrieved the incident but failed the cross-document project join and returned no project name. |

## Samsung candidate-fate proof

The correct answer is present in the index. Qdrant contains 24 active chunks on
manual pages 51–53; the consolidated page chunks collectively contain the
complete 14-item equipment list.

The exhaustive document scan produces 238 active points and 236 chunks after
content deduplication. Replaying the production pre-rerank selection policy
places the relevant chunks at positions 66–85 and 197–200. With
`rag_reranker_max_candidates=40`, **zero chunks from pages 51–53 enter the
cross-encoder**. The reranker therefore cannot recover the correct evidence.

The isolated live query confirms the downstream effect:

- diagnostic pages: 4, 8, 9, 11, 25, 37, 56, 67, and 100;
- final cited pages: 4, 25, and 67;
- required pages: 51, 52, and 53;
- failure stages: retrieval and answer content.

This proves that the Samsung failure is not missing ingestion and not a
cross-encoder inference failure. Its first deterministic failure is the
candidate-cap selection policy before reranking. The companion
`ranking-gold.json` requires all three pages so this regression can be tested
without relying on the current evaluator's any-page source-page check.
