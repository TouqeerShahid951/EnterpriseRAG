# PDF Source Highlighting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Use subagent-driven development only when separately authorized. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** Planned; no application changes or reingestion performed for this plan.

**Goal:** Locate cited PDF passages using stored geometry first and conservative page-local text matching when geometry is absent.

**Architecture:** Ingestion owns original text, page identity, provenance, and coordinates. The documents viewer owns fallback matching against PDF.js's rendered text layer and displays the match outcome. Query generation stays single-pass; opening a source does not call an LLM or change the answer.

**Tech Stack:** Existing Python/Pydantic ingestion contracts, PyMuPDF/Docling, React/TypeScript, PDF.js 4.10, Vitest, pytest; Node 22 and npm 10. No new runtime dependency.

**Spec:** The user's approved direction in this conversation: preserve PDF coordinates, store page-local text targets, use PDF.js text matching when coordinates are missing, and retain an unavailable state for unsafe matches. This document records that design and its execution steps.

## Global constraints

- Preserve document permissions, current-generation checks, content hashes, and evidence hashes.
- Preserve existing citation labels, answer streaming, provider budgets, and faithfulness settings.
- Source-location matching establishes where text appears; it does not establish claim support.
- No fuzzy similarity, model-generated quotations, OCR calls, or automatic answer withdrawal.
- Existing generated descriptions must not be treated as original document text.
- Keep document content and secrets out of logs; diagnostics contain counts and reason codes only.
- The worktree contains extensive existing changes. Stage or commit only reviewed task hunks if commits are requested; never reset or commit whole directories.
- Deployment and reingestion are rollout steps after implementation validation, not actions authorized by this planning request.

## Evidence and compatibility boundary

The inspected Zero Trust source is document `2ae2a81a-cf69-4366-896f-7da4eab28fc3`, chunk `:47`, generation `9b3133e4-f7da-5c49-9824-5449f20cc2d7`.

It has a chunk page range of 6–7, one `kind: text` citation target, no target page or bounding box, and missing provenance. Its target includes native text and an appended image description. The PDF viewer accepts only coordinate regions today; DOCX alone receives text targets. Thus the recent DOCX normalization change cannot fix this PDF.

Parser flags show a mixed fallback extraction path, but do not identify exactly where coordinates were lost. Trace parser output through chunking and indexed payloads before changing that path. Reingestion is not a guaranteed fix until this trace is verified.

Compatibility policy:

| Source target | Viewer behavior |
| --- | --- |
| Valid page geometry | Render the stored region, identified as a source region |
| Native text, known page, missing geometry | Match the complete target on that page; highlight a unique occurrence |
| OCR text with valid geometry | Render the region with the existing OCR caveat |
| OCR without geometry, generated description, unknown provenance | Show why precise location is unavailable |
| Legacy text target without page | Keep existing page navigation and request reingestion; do not guess a page |
| Repeated text without disambiguating context | Report ambiguous match; do not choose the first occurrence |

The cited Zero Trust generation belongs in the legacy row. New native PDF targets and old targets that already have explicit native provenance and page identity can use the fallback. Broad legacy targets will not be split heuristically in the browser.

## Task 1: Preserve page-local source anchors through ingestion

**Files:**
- Modify `backend/src/rag/shared/contracts/evidence.py` and `frontend/src/types/query.ts` for additive text-target metadata.
- Modify `backend/src/rag/ingestion/chunking/citation_targets.py` for target selection.
- Inspect `backend/src/rag/ingestion/parsers/pdf/pymupdf.py`, `parsers/context.py`, `parsers/models.py`, `parsers/docling/adapter.py`, `parsers/pdf/ocr_reconciliation.py`, `chunking/text.py`, and `chunking/chunker.py`; modify only the boundary demonstrated to lose source locations.
- Test `backend/tests/ingestion/test_citation_targets.py`, `backend/tests/ingestion/test_parser_integrity.py`, and `backend/tests/query/sources/test_citation_target_mapping.py`.
- Update affected public query/ingestion OpenAPI contracts under `backend/tests/architecture/`.

**Interface:** Keep `kind: text`; add optional `page: int | None = None` with `ge=1` in Python and `page?: number | null` in TypeScript. Carry existing per-target `provenance_kind` into the frontend union as an optional backward-compatible field. Keep the required bounding box on `kind: page`; no new union variant or database table.

- [ ] Add and run failing tests covering a native one-page item without a box, two native items on different pages, a merged native/vision chunk, and a source span with a box when the enclosing item has none. Example:

```python
def test_native_pdf_text_fallback_retains_its_page():
    item = ParsedPdfItem(index=0, text="Records must be retained.",
        item_type="text", page_start=6, page_end=6,
        quality_flags=["source:pymupdf_native"])
    target = citation_targets([item])[0]
    assert target["kind"] == "text"
    assert target["page"] == 6
    assert target["provenance_kind"] == "native"
```

- [ ] Trace the Zero Trust source's original native blocks through the parser and chunker using an isolated parse/check, without publishing an index. Compare page, bbox, source-span count, and target count at each boundary. Do not print source text.
- [ ] Keep exact native text distinct from contextual headings or generated descriptions. When native blocks merge, preserve their original spans rather than assign the merged text one guessed rectangle. If span geometry is available, emit `kind: page` even when the parent item has no bbox. Keep DOCX/PPTX/image-specific target handling intact.
- [ ] For a native item lacking geometry, emit page-local fallback metadata only when `page_start == page_end` and a positive page is known. A multi-page item without retained spans stays unlocatable. Use the existing original-text provenance rules; never infer native provenance from a mixed chunk's aggregate flags.

```python
# At the native PDF text fallback branch, after provenance is resolved:
target = {"kind": "text", "exact_text": original_text,
          "provenance_kind": "native"}
if item.page_start is not None and item.page_start == item.page_end:
    target["page"] = item.page_start
```

- [ ] Verify serialization through review save/resume, Qdrant payload construction, `source_from_hit`, and the source endpoint preserves optional page and provenance. Legacy payloads must still validate. Invalid page zero must fail boundary validation.
- [ ] Run the focused ingestion/source tests and architecture contracts, inspect the diff, and record results before moving on.

## Task 2: Implement conservative text matching with stable source offsets

**Files:**
- Create `frontend/src/features/documents/utils/pdfTextMatching.ts` and `pdfTextMatching.test.ts`.
- Reuse and, where required, extract normalization into `frontend/src/features/documents/utils/sourceTextNormalization.ts` with `sourceTextNormalization.test.ts`.
- Update `documentRegionViewerUtils.ts` and its tests only to share the normalization implementation and protect DOCX behavior.

**Interfaces:**

```ts
export interface NormalizedSourceText {
  text: string;
  // UTF-16 source intervals, one interval per normalized UTF-16 code unit.
  spans: Array<{ start: number; end: number }>;
}
export function normalizeSourceTextWithOffsets(value: string): NormalizedSourceText;

export type PdfTextMatch =
  | { status: "matched"; start: number; end: number }
  | { status: "not_found" | "ambiguous" };
export function matchPdfText(text: string, target: {
  exact_text: string; prefix?: string; suffix?: string;
}): PdfTextMatch;
```

- [ ] Add failing tests for complete matches across whitespace and split text runs, smart quotes, soft hyphens, ligatures, Unicode expansion, and combining characters. Assert returned offsets against the original input, not a second call to the normalizer.

```ts
expect(matchPdfText("Heading\nRecords must be retained.\nEnd", {
  exact_text: "Records must be retained.",
})).toEqual({ status: "matched", start: 8, end: 33 });
expect(matchPdfText("Records. Records.", {
  exact_text: "Records.",
})).toEqual({ status: "ambiguous" });
expect(matchPdfText("Records must be deleted.", {
  exact_text: "Records must be retained.",
})).toEqual({ status: "not_found" });
```

- [ ] Reuse native normalization primitives with an offset map. Apply identical normalization to target and rendered text. Preserve digits, punctuation distinctions that carry meaning, and word boundaries; never remove ordinary line-ending hyphens speculatively.
- [ ] Correct the existing indiscriminate `/n`, `/r`, `/t` replacement before sharing it with PDF matching: `/network`, URLs, paths, and ratios are real text. Literal backslash sequences also require provenance-aware handling; do not globally unescape document text. Add negative cases such as `/reports` versus ` eports` and a literal `C:\\new` path. Actual newlines/tabs remain supported. Ambiguous parser escape artifacts should remain unavailable until corrected at their source.
- [ ] Find all normalized exact matches, apply prefix/suffix disambiguation, return only a unique result, and map its endpoints back to source offsets. Do not use the schema's default occurrence zero as evidence that the first occurrence is correct.
- [ ] Verify real highlighted substrings and boundaries in a rendered DOM during Task 3; mocked range calls alone do not prove offsets are correct. Run both PDF matcher and existing DOCX tests.

## Task 3: Render and navigate PDF fallback highlights

**Files:**
- Modify `frontend/src/features/documents/components/DocumentRegionViewer.tsx`.
- Modify `frontend/src/features/documents/components/source-viewer/PdfRegionDocument.tsx`.
- Create `frontend/src/features/documents/components/source-viewer/PdfTextHighlights.ts` for PDF-specific text-layer lifecycle and range rectangles, with `PdfTextHighlights.test.ts`.
- Modify `frontend/src/features/source-viewer/utils/sourceViewer.ts` and its tests.
- Modify `frontend/src/styles/source-viewer/pdf.css` for text-match overlays.

**Interfaces:** PDF viewer receives the original typed `CitationTarget[]` alongside `regions`. PDF text-layer code consumes one loaded `PDFPageProxy`, its viewport, and eligible targets for that page. It returns per-target outcomes (`matched`, `not_found`, `ambiguous`, `unsupported`) plus DOM rectangles relative to that page. Use PDF.js's installed text-layer API; inspect its local types/examples before choosing exact lifecycle calls.

- [ ] Add failing integration cases: page-local native text with no region, geometry present, target on a later page, repeated text, scanned page without a text layer, and document/page switch during asynchronous matching.
- [ ] Pass text targets into the PDF branch. Render the PDF.js text layer aligned with the canvas, map its ordered text nodes using the source-offset utility, and use DOM ranges to measure matching fragments. Keep whitespace boundaries between paragraphs/lines; do not join unrelated columns into one sentence.
- [ ] Enable fallback only for a native target with an explicit page and no usable coordinates. Match complete target text, never only the beginning or query keywords. Use each target's provenance rather than the source's aggregate provenance.

```ts
const eligible = citationTargets.filter(target =>
  target.kind === "text" && target.page === pageNumber &&
  target.provenance_kind === "native");
```

- [ ] Keep stored geometry as the first route. For text fallback use text-layer rectangles, not proportional estimates from whole text-item width. Verify rotation/crop and zoom alignment with actual PDF fixtures. Do not silently call a block rectangle a character-exact quote.
- [ ] Open a page that actually contains a target, falling back to chunk page metadata only when target pages are absent. Provide previous/next cited-page navigation for chunks spanning multiple pages. Multiple matched targets remain distinct; this release does not choose which passage supports an individual answer sentence.
- [ ] Tie async work to document revision/page identity; cancel and clear old text layers/overlays on navigation and unmount. Recompute rectangles after zoom/render completion and ignore stale completion callbacks.
- [ ] Read text only for the viewed page; reuse its text content during zoom in that viewer instance. Do not pre-scan the complete PDF, persist a global cache, or add backend/model calls. Keep UI navigation responsive.
- [ ] Inspect the resulting marks on real rendered PDFs, including a rotated/cropped page and multi-column layout. If reading order is ambiguous, return unavailable rather than a misleading highlight.

## Task 4: Explain location availability accurately

**Files:**
- Modify the PDF viewer and its existing `DocumentRegionViewerPrimitives.tsx` fallback presentation.
- Modify `frontend/src/features/chat/components/EvidenceWindows.tsx` and `EvidenceInspector.tsx` only for misleading terminal status text.
- Modify `backend/src/rag/query/answering/faithfulness.py` only if terminal skip paths leave `attribution_status: pending`.
- Extend existing chat/source tests and backend faithfulness tests.

**Interface:** Viewer outcomes describe location (`stored region`, `text matched`, `partially located`, `unavailable`). Existing faithfulness/attribution fields continue to describe claim support; matching never sets a claim to verified.

- [ ] Add failing cases for missing page metadata, no text layer, ambiguous text, and a mixed chunk with one locatable and one unlocatable target. A successful target must not mask failure of the others.
- [ ] Show concise reasons: “This older citation has no page-level location. Reingest the document to rebuild it.”, “Text could not be located on this page.”, or “This text appears more than once; an exact location is unavailable.” A file-rendering error must remain an operational error with retry, rather than a no-match result.
- [ ] Reproduce the screenshot's completed query with faithfulness disabled. If its sources remain `pending`, set terminal skipped/unattributed sources to the existing `unavailable` state and display “Claim support was not checked.” Do not schedule a new attribution job or alter the skip policy.

```python
# In an existing terminal skip branch, preserving all other source fields:
sources = [source.model_copy(update={"attribution_status": "unavailable"})
           if source.attribution_status == "pending" else source
           for source in sources]
```

- [ ] Verify that unknown extraction provenance remains unknown and that query-keyword match counts are not labelled exact source locations. Cover completed saved responses and streamed responses using the existing state paths.

## Task 5: Validate and roll out on representative sources

**Files:** Update `backend/src/rag/ingestion/README.md` and the applicable source-viewing section of `docs/manuals/`; regenerate manual outputs using `scripts/build_user_manuals.py` if manual source changes.

- [ ] Run focused tests after each task, then the final frontend and cross-boundary checks:

```bash
npm --prefix frontend test
npm --prefix frontend run build
uv run --directory backend --locked --extra dev python -m pytest tests/ingestion/test_citation_targets.py tests/ingestion/test_parser_integrity.py tests/query/sources/test_citation_target_mapping.py tests/documents/test_source_revision.py
uv run --directory backend --locked --extra dev python -m pytest tests/architecture
docker compose config --quiet
```

- [ ] Run any additional parser, review-resume, or faithfulness suites corresponding to files actually changed. Check the touched files with Ruff and scoped `git diff --check`; do not repair unrelated dirty files.
- [ ] Build affected API, ingestion-worker, and frontend images. Verify imports/health and the served frontend bundle. For additive metadata deploy compatible readers before enabling writers to publish new targets.
- [ ] Reingest only the Zero Trust PDF as the first rollout sample after authorization. Preserve the existing active generation until a replacement successfully completes review and indexing. Do not reingest the entire collection.
- [ ] Before publishing the sample, verify the section-five paragraph and its figure remain distinct evidence items, target pages agree with the source, and native paragraphs have valid geometry or eligible page-local text. If coordinates are still lost, fix that boundary before retrying; repeating the same ingestion is not a repair.
- [ ] Ask the original pillars question against the new generation. Open its citation, confirm the paragraph is visibly located, and separately exercise the text-only fallback with a controlled native PDF fixture. Geometry success alone does not test fallback matching.
- [ ] Reopen a saved old-generation citation: show revision unavailability when appropriate; never retarget it silently to the new generation. Also test a scan, a DOCX, and a citation spanning pages.
- [ ] Record visible match outcomes and viewer timing on the representative PDFs. Confirm no additional model calls or change to answer latency path. Report reingestion needs for other legacy documents without scheduling bulk work.

## Acceptance criteria

- Complete native PDF targets without boxes highlight correctly when page identity and rendered text are available.
- Coordinate targets, DOCX matching, source access controls, and revision checks remain functional.
- Ambiguous, generated, unknown-provenance, or unlocatable targets produce an honest availability state.
- Zoom, rotated/cropped pages, and navigation do not misplace or leave stale marks.
- Zero Trust is verified against a newly validated generation, with the original legacy limitation documented.
- Skipped claim attribution does not appear to be processing indefinitely.
- No extra generation pass, no automatic answer withdrawal, no new runtime dependency, and no bulk reingestion.

## Deferred work

Sentence-to-target selection, fuzzy OCR correction, reconstructing arbitrary legacy mixed chunks, automatic corpus-wide repair, and new faithfulness controls are outside this plan. They are separate behaviors with different correctness requirements.
