# Source Viewer Document Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add in-preview phrase search for every text-bearing source format supported by the browser viewer.

**Architecture:** Keep search state inside each renderer because result navigation differs by format. Reuse one small controlled toolbar component for the shared search interaction, and use existing PDF.js, DOCX DOM, JSON text, and XLSX parsing already loaded by the viewer. PDF, DOCX, JSON, CSV, and XLSX search locally; PPTX and image previews show an explicit unavailable state because the current viewer receives rendered images rather than searchable source text.

**Tech Stack:** React 18, TypeScript, Vitest, PDF.js, `docx-preview`, `@e965/xlsx`, existing source-viewer CSS tokens.

**Spec:** In-chat approved source-viewer search design; this is a bounded change with no separate spec document.

## Global Constraints

- Do not add a backend route, persisted state, parser dependency, or API client method.
- Search is case-insensitive and treats runs of whitespace as one space.
- Preserve existing citation highlights, page/slide navigation, zoom controls, and revision-aware document loading.
- Keep image and rendered-PPTX search unavailable rather than implying that bitmap pixels are searchable.
- Use semantic labels, keyboard-submit with Enter, visible focus, live result status, and reduced-motion-compatible styling.
- Do not stage or modify unrelated existing worktree changes.

## File Map

- Create `frontend/src/features/documents/components/source-viewer/SourceViewerSearch.tsx`: controlled search form and result navigation controls.
- Create `frontend/src/features/documents/components/source-viewer/SourceViewerSearch.test.tsx`: markup/accessibility contract for the shared control.
- Modify `frontend/src/features/source-viewer/utils/sourceViewer.ts` and `.test.ts`: normalized text ranges and matching-page helpers.
- Modify `frontend/src/features/documents/utils/documentRegionViewerUtils.ts` and `.test.ts`: rendered-DOCX match counting and active-match highlighting, reusing the existing text index.
- Modify `PdfRegionDocument.tsx`, `DocxRegionDocument.tsx`, `JsonRegionDocument.tsx`, `SpreadsheetRegionDocument.tsx`, and `ImageRegionDocument.tsx` plus their colocated tests: renderer-specific search and explicit bitmap limitation.
- Modify `frontend/src/styles/source-viewer/shell-and-toolbar.css`, `docx.css`, `json.css`, and `spreadsheet.css`: compact toolbar, active-match, and cell-match styles.
- Modify `docs/manuals/end-user-manual.md`: document search behavior and unsupported bitmap previews; regenerate manuals with the existing builder.

### Task 1: Add the shared search contract and normalized text helpers

**Files:**
- Create: `frontend/src/features/documents/components/source-viewer/SourceViewerSearch.tsx`
- Test: `frontend/src/features/documents/components/source-viewer/SourceViewerSearch.test.tsx`
- Modify: `frontend/src/features/source-viewer/utils/sourceViewer.ts`
- Test: `frontend/src/features/source-viewer/utils/sourceViewer.test.ts`

**Interfaces:**
- `SourceViewerSearch` consumes `query`, `disabled`, `isSearching`, `resultLabel`, `status`, `onQueryChange`, `onSearch`, `onPrevious`, and `onNext`.
- `sourceTextMatchRanges(text: string, query: string): Array<{ start: number; end: number }>` returns non-overlapping, case-insensitive matches while allowing whitespace differences.
- `sourceTextMatchPages(pages: string[], query: string): number[]` returns one-based page numbers whose text contains at least one match.

- [ ] **Step 1: Write the failing utility tests.**

  Add to `sourceViewer.test.ts`:

  ```ts
  it("matches text across case and whitespace differences", () => {
    expect(sourceTextMatchRanges("Space\nResources are useful", "space resources")).toEqual([{ start: 0, end: 15 }]);
    expect(sourceTextMatchPages(["first page", "SPACE   RESOURCES", "last page"], "space resources")).toEqual([2]);
    expect(sourceTextMatchPages(["page one"], "")).toEqual([]);
  });
  ```

  Add to `SourceViewerSearch.test.tsx`:

  ```tsx
  it("renders an accessible search field and result navigation", () => {
    const markup = renderToStaticMarkup(
      <SourceViewerSearch
        query="space"
        resultLabel="1 of 2"
        status="Found on page 2"
        onNext={() => undefined}
        onPrevious={() => undefined}
        onQueryChange={() => undefined}
        onSearch={() => undefined}
      />,
    );
    expect(markup).toContain('role="search"');
    expect(markup).toContain('type="search"');
    expect(markup).toContain('aria-label="Search document"');
    expect(markup).toContain("1 of 2");
  });
  ```

- [ ] **Step 2: Run the focused tests and confirm the expected red failure.**

  Run:

  ```bash
  npm --prefix frontend test -- src/features/source-viewer/utils/sourceViewer.test.ts src/features/documents/components/source-viewer/SourceViewerSearch.test.tsx
  ```

  Expected: FAIL because the new exports and component do not exist yet.

- [ ] **Step 3: Implement the smallest shared contract.**

  Export the two range/page helpers from `sourceViewer.ts`. Normalize only the query and source whitespace/case needed for search; preserve original offsets in `sourceTextMatchRanges` so JSON highlighting can map back to the displayed string. Implement `SourceViewerSearch` as a `<form role="search">` with a labeled native `type="search"` input, submit button, live status, and disabled previous/next buttons when `resultLabel` is absent.

- [ ] **Step 4: Run the focused tests and typecheck the new contract.**

  Run:

  ```bash
  npm --prefix frontend test -- src/features/source-viewer/utils/sourceViewer.test.ts src/features/documents/components/source-viewer/SourceViewerSearch.test.tsx
  npm --prefix frontend run typecheck
  ```

  Expected: PASS with no TypeScript errors.

### Task 2: Reuse the existing rendered-text index for DOCX search

**Files:**
- Modify: `frontend/src/features/documents/utils/documentRegionViewerUtils.ts`
- Test: `frontend/src/features/documents/utils/documentRegionViewerUtils.test.ts`

**Interfaces:**
- `countRenderedTextMatches(root: HTMLElement, query: string): number` counts normalized matches without mutating the DOM.
- `highlightRenderedTextMatch(root: HTMLElement, query: string, occurrence: number): boolean` wraps only the requested normalized occurrence in `mark.source-viewer-search-highlight`.

- [ ] **Step 1: Add failing tests using the existing text-node test harness.**

  Add tests for two occurrences split across rendered nodes and for a missing query:

  ```ts
  it("counts and highlights the requested rendered-text occurrence", () => {
    const firstBlock = {} as Element;
    const secondBlock = {} as Element;
    const nodes = [textNode("Space", firstBlock), textNode(" resources", firstBlock), textNode("Space resources", secondBlock)];
    const surroundContents = mockRenderedText(nodes);

    expect(countRenderedTextMatches({} as HTMLElement, "space resources")).toBe(2);
    expect(highlightRenderedTextMatch({} as HTMLElement, "space resources", 1)).toBe(true);
    expect(surroundContents).toHaveBeenCalled();
    expect(highlightRenderedTextMatch({} as HTMLElement, "missing", 0)).toBe(false);
  });
  ```

- [ ] **Step 2: Run the focused test and confirm it fails for the missing exports.**

  Run:

  ```bash
  npm --prefix frontend test -- src/features/documents/utils/documentRegionViewerUtils.test.ts
  ```

  Expected: FAIL before implementation.

- [ ] **Step 3: Implement both functions on top of `indexRenderedText`.**

  Normalize the indexed text and query using the existing normalization rules, locate non-overlapping occurrences, and reuse `wrapMatchedText` with a separate `source-viewer-search-highlight` class. Leave `highlightExactSourceText` and its citation class unchanged. The functions must return `0`/`false` for empty or missing queries and must not catch or hide `Range` failures.

- [ ] **Step 4: Run the utility tests and confirm the existing citation tests remain green.**

  Run:

  ```bash
  npm --prefix frontend test -- src/features/documents/utils/documentRegionViewerUtils.test.ts
  ```

  Expected: PASS for all rendered-text and citation cases.

### Task 3: Add PDF page search

**Files:**
- Modify: `frontend/src/features/documents/components/source-viewer/PdfRegionDocument.tsx`
- Create: `frontend/src/features/documents/components/source-viewer/PdfRegionDocument.test.tsx`

**Interfaces:**
- Search runs against each PDF page's `getTextContent()` result and passes the joined `str` values to `sourceTextMatchPages`.
- Search result state is local to the PDF renderer: matching one-based pages, active result index, submitted query, loading flag, and status message.

- [ ] **Step 1: Add a failing component contract test.**

  Mock the PDF worker/document import as needed by the existing Vitest setup and render the component with no loaded document. Assert that the toolbar contains the labeled search field and that a submit control exists. Add a second test around the pure `sourceTextMatchPages` contract for pages 1 and 3 so the navigation target is unambiguous.

- [ ] **Step 2: Run the focused test and verify it fails before the toolbar exists.**

  Run:

  ```bash
  npm --prefix frontend test -- src/features/documents/components/source-viewer/PdfRegionDocument.test.tsx
  ```

  Expected: FAIL because the PDF toolbar has no search control yet.

- [ ] **Step 3: Implement PDF search with existing PDF.js data.**

  Add `SourceViewerSearch` beside the page and zoom controls. On submit, trim the query; clear results for an empty query; otherwise load every page's text content, collect page matches, select the first matching page at or after the current page (wrapping to the first result), and set `pageNumber` to that page. Previous/next wrap through the matching-page list and update `pageNumber`. Use a request id ref so a slower older search cannot overwrite a newer one. Reset search state when a new PDF buffer opens. Display `Searching…`, `No matches`, or the current `N of M` result label through `aria-live` status.

- [ ] **Step 4: Run the PDF tests and frontend typecheck.**

  Run:

  ```bash
  npm --prefix frontend test -- src/features/documents/components/source-viewer/PdfRegionDocument.test.tsx src/features/source-viewer/utils/sourceViewer.test.ts
  npm --prefix frontend run typecheck
  ```

  Expected: PASS with no unused imports or state warnings.

### Task 4: Add DOCX and JSON search/highlighting

**Files:**
- Modify: `frontend/src/features/documents/components/source-viewer/DocxRegionDocument.tsx`
- Test: `frontend/src/features/documents/components/source-viewer/DocxRegionDocument.test.tsx`
- Modify: `frontend/src/features/documents/components/source-viewer/JsonRegionDocument.tsx`
- Create: `frontend/src/features/documents/components/source-viewer/JsonRegionDocument.test.tsx`

**Interfaces:**
- DOCX search uses the existing rendered container and the Task 2 functions; the active occurrence is re-rendered after each search navigation so old search marks cannot remain.
- JSON search uses `sourceTextMatchRanges(displayText, query)` and passes all ranges plus the active range to line rendering without removing existing JSON syntax coloring outside marks.

- [ ] **Step 1: Add failing renderer tests.**

  Extend the DOCX test to assert that the normal document toolbar includes `Search document`. Add a JSON test using a small encoded object and assert that the normal preview toolbar includes the same field; the range helper test from Task 1 covers the matching offsets used by the renderer.

- [ ] **Step 2: Run both focused tests and verify the new assertions fail.**

  Run:

  ```bash
  npm --prefix frontend test -- src/features/documents/components/source-viewer/DocxRegionDocument.test.tsx src/features/documents/components/source-viewer/JsonRegionDocument.test.tsx
  ```

  Expected: FAIL because neither renderer currently mounts the shared search control.

- [ ] **Step 3: Implement DOCX search.**

  Add controlled query/result state to `DocxRegionDocument`. Include the search control in both the normal document toolbar and the existing extracted-image-only toolbar with search disabled there. On search, count matches from the rendered container; on previous/next, change the active occurrence; rerun the existing render effect, apply citation marks, then call `highlightRenderedTextMatch` for the active occurrence and scroll the resulting mark into view. Report `No matches` when the count is zero.

- [ ] **Step 4: Implement JSON search.**

  Add query/range/active-index state. Search the already-selected `displayText`, keep all ranges, and render a `source-viewer-json-search-highlight` mark for the active range plus a less-emphasized class for other matches. Keep the existing JSON pointer highlight behavior and show the search result count in the shared control. When the query is empty, remove search marks and leave pointer highlighting intact.

- [ ] **Step 5: Run focused tests and typecheck.**

  Run:

  ```bash
  npm --prefix frontend test -- src/features/documents/components/source-viewer/DocxRegionDocument.test.tsx src/features/documents/components/source-viewer/JsonRegionDocument.test.tsx src/features/documents/utils/documentRegionViewerUtils.test.ts
  npm --prefix frontend run typecheck
  ```

  Expected: PASS with existing image-evidence and citation behavior preserved.

### Task 5: Add CSV/XLSX cell search and bitmap limitation messaging

**Files:**
- Modify: `frontend/src/features/documents/components/source-viewer/SpreadsheetRegionDocument.tsx`
- Test: `frontend/src/features/documents/components/source-viewer/SpreadsheetRegionDocument.test.tsx`
- Modify: `frontend/src/features/documents/components/source-viewer/ImageRegionDocument.tsx`
- Create: `frontend/src/features/documents/components/source-viewer/ImageRegionDocument.test.tsx`

**Interfaces:**
- `findSpreadsheetMatches(workbook: XLSX.WorkBook, query: string): Array<{ sheetName: string; row: number; column: number }>` scans formatted cell values and returns zero-based coordinates.
- Spreadsheet preview receives the active search coordinate as its preview anchor, so a match outside the citation window becomes visible without removing the existing 500-row/50-column safety limits.

- [ ] **Step 1: Add failing spreadsheet and bitmap tests.**

  Add a CSV fixture with two sheets/cells and assert that `findSpreadsheetMatches` returns the sheet and coordinates for a case-insensitive query. Add a static render assertion for `Text search is unavailable for image-only previews` in `ImageRegionDocument`.

- [ ] **Step 2: Run the focused tests and verify they fail before implementation.**

  Run:

  ```bash
  npm --prefix frontend test -- src/features/documents/components/source-viewer/SpreadsheetRegionDocument.test.tsx src/features/documents/components/source-viewer/DocxRegionDocument.test.tsx
  ```

  Expected: FAIL because the search export, toolbar, and bitmap message do not exist.

- [ ] **Step 3: Implement workbook search and navigation.**

  Scan each sheet's declared `!ref`, use `XLSX.utils.format_cell(cell)`, and match with `sourceTextMatchRanges`. On submit, select the first result, switch to its sheet, and use its cell as the preview anchor. Previous/next wrap through all matching cells. Mark matching visible cells with a search class and the active cell with an active class; retain `is-cited` independently.

- [ ] **Step 4: Implement the explicit image-only limitation.**

  Add a short status message beside the existing image toolbar label. Because PPTX slides already render through `ImageRegionDocument`, the same message covers both standalone images and rendered slides without a second PPTX-specific search path. Keep DOCX extracted-image evidence on its existing image-only path and do not claim that its OCR caption is a full-document search index.

- [ ] **Step 5: Run focused tests and typecheck.**

  Run:

  ```bash
  npm --prefix frontend test -- src/features/documents/components/source-viewer/SpreadsheetRegionDocument.test.tsx src/features/documents/components/source-viewer/DocxRegionDocument.test.tsx
  npm --prefix frontend run typecheck
  ```

  Expected: PASS with cited-cell styling, sheet selection, slide rendering, and image evidence unchanged.

### Task 6: Style, document, and verify the complete slice

**Files:**
- Modify: `frontend/src/styles/source-viewer/shell-and-toolbar.css`
- Modify: `frontend/src/styles/source-viewer/docx.css`
- Modify: `frontend/src/styles/source-viewer/json.css`
- Modify: `frontend/src/styles/source-viewer/spreadsheet.css`
- Modify: `docs/manuals/end-user-manual.md`
- Regenerate: `docs/manuals/generated/` using `scripts/build_user_manuals.py`

- [ ] **Step 1: Add failing style/document assertions where the existing test setup can observe them.**

  Extend the shared search test to assert the result controls expose `aria-label="Previous search result"` and `aria-label="Next search result"`. Add the manual text explaining that text-bearing previews search locally and bitmap-only previews require the original file/OCR workflow.

- [ ] **Step 2: Run the focused assertion and confirm the new labels are absent.**

  Run:

  ```bash
  npm --prefix frontend test -- src/features/documents/components/source-viewer/SourceViewerSearch.test.tsx
  ```

  Expected: FAIL until the labels and styles are added.

- [ ] **Step 3: Add compact responsive styles.**

  Style the search group using existing source-viewer spacing, borders, colors, and focus ring tokens. Keep the input usable at 320px, allow the toolbar to wrap at 720px, distinguish active search marks from citation marks, and ensure cell matches remain readable with or without color.

- [ ] **Step 4: Regenerate the tracked manual artifacts.**

  Run:

  ```bash
  python scripts/build_user_manuals.py
  ```

  Review the generated diff and retain only the expected manual regeneration output; do not hand-edit files under `docs/manuals/generated/`.

- [ ] **Step 5: Run the complete frontend verification set.**

  Run:

  ```bash
  npm --prefix frontend test
  npm --prefix frontend run typecheck
  npm --prefix frontend run build
  npm --prefix frontend run check:dead-code
  ```

  Expected: all commands exit 0 with no test failures, TypeScript errors, build errors, or dead-code findings.

- [ ] **Step 6: Manually verify the browser flow.**

  Open a PDF, DOCX, JSON, CSV/XLSX, PPTX, and image preview. Search a phrase that occurs on a later page/sheet, press Enter, use previous/next, confirm the active location is visible, confirm empty/no-match status is announced, and confirm PPTX/image previews state that text search is unavailable. Check keyboard Tab/Enter behavior and the 320px and desktop toolbar layouts.

- [ ] **Step 7: Review the final diff boundary.**

  Run:

  ```bash
  git status --short
  git diff --check
  git diff --stat -- frontend/src docs/manuals
  ```

  Confirm that only the planned source-viewer files, tests, styles, manual source, and generated manual outputs changed; leave all unrelated pre-existing modifications untouched.
