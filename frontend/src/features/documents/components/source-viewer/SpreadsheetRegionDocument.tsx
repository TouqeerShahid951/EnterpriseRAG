import { useMemo, useState, type ReactNode } from "react";
import * as XLSX from "@e965/xlsx";

import { FallbackNotice, SourceViewerError } from "@/features/documents/components/source-viewer/DocumentRegionViewerPrimitives";
import { SourceViewerSearch } from "@/features/documents/components/source-viewer/SourceViewerSearch";
import { sourceTextMatchRanges } from "@/features/source-viewer/utils/sourceViewer";
import type { CitationTarget } from "@/types/query";

const MAX_PREVIEW_ROWS = 500;
const MAX_PREVIEW_COLUMNS = 50;
const CONTEXT_ROWS = 10;
const CONTEXT_COLUMNS = 3;

type SpreadsheetTarget = Extract<CitationTarget, { kind: "spreadsheet" }>;

export interface SpreadsheetSearchMatch {
  column: number;
  row: number;
  sheetName: string;
}

export function findSpreadsheetMatches(workbook: XLSX.WorkBook, query: string): SpreadsheetSearchMatch[] {
  if (!query.trim()) return [];
  const matches: SpreadsheetSearchMatch[] = [];
  for (const sheetName of workbook.SheetNames) {
    const sheet = workbook.Sheets[sheetName];
    if (!sheet?.["!ref"]) continue;
    const range = XLSX.utils.decode_range(sheet["!ref"]);
    for (let row = range.s.r; row <= range.e.r; row += 1) {
      for (let column = range.s.c; column <= range.e.c; column += 1) {
        const cell = sheet[XLSX.utils.encode_cell({ r: row, c: column })];
        if (cell && sourceTextMatchRanges(XLSX.utils.format_cell(cell), query).length) matches.push({ column, row, sheetName });
      }
    }
  }
  return matches;
}

export function SpreadsheetRegionDocument({
  buffer,
  documentTitle,
  fallbackMessage,
  targets,
  toolbarEnd,
}: {
  buffer: ArrayBuffer;
  documentTitle: string;
  fallbackMessage: string;
  targets: SpreadsheetTarget[];
  toolbarEnd?: ReactNode;
}) {
  const workbook = useMemo(() => {
    try {
      return XLSX.read(buffer, { type: "array" });
    } catch {
      return null;
    }
  }, [buffer]);
  const [sheetName, setSheetName] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [searchMatches, setSearchMatches] = useState<SpreadsheetSearchMatch[]>([]);
  const [searchIndex, setSearchIndex] = useState(-1);
  const [searchStatus, setSearchStatus] = useState<string | undefined>();
  if (!workbook) return <SourceViewerError message="The spreadsheet could not be opened." />;
  const loadedWorkbook = workbook;

  const targetSheet = targets.find((target) => loadedWorkbook.SheetNames.includes(target.sheet_name))?.sheet_name;
  const activeSearchMatch = searchMatches[searchIndex] ?? null;
  const selectedSheetName = sheetName || activeSearchMatch?.sheetName || targetSheet || loadedWorkbook.SheetNames[0] || "";
  const sheetTargets = loadedWorkbook.SheetNames.length === 1
    ? targets
    : targets.filter((target) => target.sheet_name === selectedSheetName);
  const sheetSearchMatches = searchMatches.filter((match) => match.sheetName === selectedSheetName);
  const preview = spreadsheetPreview(loadedWorkbook.Sheets[selectedSheetName], sheetTargets, sheetSearchMatches, activeSearchMatch);
  const hasHighlight = preview.rows.some((row) => row.cells.some((cell) => cell.cited));

  function resetSearch() {
    setSearchMatches([]);
    setSearchIndex(-1);
    setSearchStatus(undefined);
  }

  function runSearch() {
    const query = searchQuery.trim();
    if (!query) {
      resetSearch();
      return;
    }
    const matches = findSpreadsheetMatches(loadedWorkbook, query);
    setSearchMatches(matches);
    setSearchIndex(matches.length ? 0 : -1);
    setSearchStatus(matches.length ? undefined : "No matches");
    if (matches.length) setSheetName(matches[0].sheetName);
  }

  function goToSearchResult(direction: -1 | 1) {
    if (!searchMatches.length) return;
    const nextIndex = (searchIndex + direction + searchMatches.length) % searchMatches.length;
    setSearchIndex(nextIndex);
    setSheetName(searchMatches[nextIndex].sheetName);
  }

  return (
    <div className="source-viewer-document">
      <div className="source-viewer-toolbar">
        <div className="source-viewer-toolbar-main">
          <div className="source-viewer-file-label">{documentTitle.toLowerCase().endsWith(".csv") ? "CSV source" : "Spreadsheet source"}</div>
          {loadedWorkbook.SheetNames.length > 1 ? (
            <label className="source-viewer-sheet-label">
              <span>Sheet</span>
              <select value={selectedSheetName} onChange={(event) => setSheetName(event.target.value)}>
                {loadedWorkbook.SheetNames.map((name) => <option key={name}>{name}</option>)}
              </select>
            </label>
          ) : null}
          <SourceViewerSearch
            onNext={() => goToSearchResult(1)}
            onPrevious={() => goToSearchResult(-1)}
            onQueryChange={(query) => { setSearchQuery(query); resetSearch(); }}
            onSearch={runSearch}
            query={searchQuery}
            resultLabel={searchMatches.length ? `${searchIndex + 1} of ${searchMatches.length}` : undefined}
            status={searchStatus}
          />
        </div>
        <div className="source-viewer-toolbar-end">{toolbarEnd}</div>
      </div>
      {hasHighlight ? null : <FallbackNotice message={fallbackMessage} />}
      <div className="source-viewer-spreadsheet-scroll">
        <table className="source-viewer-spreadsheet" aria-label={`${selectedSheetName || "Spreadsheet"} preview`}>
          <tbody>
            {preview.rows.map((row) => (
              <tr key={row.index}>
                {row.cells.map((cell) => (
                  <td key={cell.index} className={[cell.cited ? "is-cited" : "", cell.searchMatch ? "is-search-match" : "", cell.activeSearchMatch ? "is-search-active" : ""].filter(Boolean).join(" ") || undefined}>{cell.value}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {preview.truncated ? <p className="source-viewer-spreadsheet-limit">Showing the cited range with nearby cells. Open the original file for the complete workbook.</p> : null}
      </div>
    </div>
  );
}

function spreadsheetPreview(sheet: XLSX.WorkSheet | undefined, targets: SpreadsheetTarget[], searchMatches: SpreadsheetSearchMatch[], activeSearchMatch: SpreadsheetSearchMatch | null) {
  if (!sheet?.["!ref"]) return { rows: [], truncated: false };
  const range = XLSX.utils.decode_range(sheet["!ref"]);
  const searchAnchor = activeSearchMatch ? {
    end_column: activeSearchMatch.column + 1,
    end_row: activeSearchMatch.row + 1,
    start_column: activeSearchMatch.column,
    start_row: activeSearchMatch.row,
  } : undefined;
  const anchor = searchAnchor ?? targets[0];
  const startRow = boundedStart(range.s.r, range.e.r, anchor?.start_row, CONTEXT_ROWS);
  const startColumn = boundedStart(range.s.c, range.e.c, anchor?.start_column, CONTEXT_COLUMNS);
  const endRow = Math.min(
    range.e.r + 1,
    startRow + MAX_PREVIEW_ROWS,
    anchor ? Math.max(startRow + 1, anchor.end_row + CONTEXT_ROWS) : range.e.r + 1,
  );
  const endColumn = Math.min(
    range.e.c + 1,
    startColumn + MAX_PREVIEW_COLUMNS,
    anchor ? Math.max(startColumn + 1, anchor.end_column + CONTEXT_COLUMNS) : range.e.c + 1,
  );
  const rows = Array.from({ length: endRow - startRow }, (_, rowOffset) => {
    const row = startRow + rowOffset;
    return {
      index: row,
      cells: Array.from({ length: endColumn - startColumn }, (_, columnOffset) => {
        const column = startColumn + columnOffset;
        const cell = sheet[XLSX.utils.encode_cell({ r: row, c: column })];
        return {
          activeSearchMatch: activeSearchMatch?.row === row && activeSearchMatch.column === column,
          cited: targets.some((target) => row >= target.start_row && row < target.end_row
            && column >= target.start_column && column < target.end_column),
          index: column,
          searchMatch: searchMatches.some((match) => match.row === row && match.column === column),
          value: cell ? XLSX.utils.format_cell(cell) : "",
        };
      }),
    };
  });
  return {
    rows,
    truncated: startRow > range.s.r || startColumn > range.s.c || endRow <= range.e.r || endColumn <= range.e.c,
  };
}

function boundedStart(minimum: number, maximum: number, targetStart: number | undefined, context: number): number {
  return targetStart === undefined ? minimum : Math.min(maximum, Math.max(minimum, targetStart - context));
}
