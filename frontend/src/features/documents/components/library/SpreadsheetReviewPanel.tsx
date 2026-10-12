import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RotateCw, Save } from "lucide-react";

import { InlineMessage } from "@/components/layout/Common";
import { documentsApi } from "@/lib/api/contracts";
import { errorMessage } from "@/lib/utils/format";
import type { SpreadsheetReviewRequest, SpreadsheetSheetReview } from "@/types/api";

type Props = {
  canEdit: boolean;
  documentId: string;
  pending: boolean;
};

export function SpreadsheetReviewPanel({ canEdit, documentId, pending }: Props) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<SpreadsheetReviewRequest | null>(null);
  const [preparing, setPreparing] = useState(false);
  const reviewQuery = useQuery({
    queryKey: ["documents", "spreadsheet-review", documentId],
    queryFn: () => documentsApi.spreadsheetReview(documentId),
    retry: false,
    refetchInterval: preparing ? 3000 : false,
  });
  useEffect(() => {
    if (reviewQuery.data) {
      setDraft({ sheets: reviewQuery.data.sheets });
      setPreparing(false);
    }
  }, [reviewQuery.data]);

  const prepareMutation = useMutation({
    mutationFn: () => documentsApi.reingest(documentId),
    onSuccess: () => setPreparing(true),
  });
  const saveMutation = useMutation({
    mutationFn: (review: SpreadsheetReviewRequest) => documentsApi.updateSpreadsheetReview(documentId, review),
    onSuccess: () => {
      setPreparing(true);
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
  });

  if (reviewQuery.isLoading && !preparing) return <p className="text-secondary">Loading table review.</p>;
  if (!draft) {
    return (
      <div className="spreadsheet-review-empty">
        <InlineMessage tone="warning">
          {preparing ? "Preparing the table review. It will appear when reingestion finishes." : errorMessage(reviewQuery.error, "This spreadsheet needs one reingestion before its tables can be reviewed.")}
        </InlineMessage>
        {canEdit && !preparing ? (
          <button type="button" className="sv-action-primary" disabled={pending || prepareMutation.isPending} onClick={() => prepareMutation.mutate()}>
            <RotateCw size={15} /> Prepare table review
          </button>
        ) : null}
      </div>
    );
  }

  const included = draft.sheets.filter((sheet) => !sheet.excluded).length;
  const busy = pending || saveMutation.isPending || preparing;
  return (
    <div className="spreadsheet-review-editor">
      <p className="text-secondary">Review every visible sheet. Saving queues a replacement index; the original file stays unchanged.</p>
      {draft.sheets.map((sheet, sheetIndex) => (
        <SheetEditor
          key={sheet.source_name}
          canEdit={canEdit}
          disabled={busy}
          sheet={sheet}
          onChange={(next) => setDraft({ sheets: draft.sheets.map((value, index) => index === sheetIndex ? next : value) })}
        />
      ))}
      {saveMutation.isError ? <InlineMessage tone="warning">{errorMessage(saveMutation.error, "The table review could not be saved.")}</InlineMessage> : null}
      {preparing ? <InlineMessage tone="success">Reindexing with the saved table schema.</InlineMessage> : null}
      {canEdit ? (
        <button type="button" className="sv-action-primary" disabled={busy || included === 0} onClick={() => saveMutation.mutate(draft)}>
          <Save size={15} /> Save and reindex
        </button>
      ) : null}
    </div>
  );
}

function SheetEditor({ canEdit, disabled, onChange, sheet }: { canEdit: boolean; disabled: boolean; onChange: (sheet: SpreadsheetSheetReview) => void; sheet: SpreadsheetSheetReview }) {
  const locked = disabled || !canEdit;
  return (
    <details className="spreadsheet-review-sheet" open>
      <summary>{sheet.source_name}<span>{sheet.excluded ? "Excluded" : `${sheet.columns.length} columns`}</span></summary>
      <div className="spreadsheet-review-sheet-body">
        <label className="spreadsheet-review-check">
          <input type="checkbox" checked={!sheet.excluded} disabled={locked} onChange={(event) => onChange({ ...sheet, excluded: !event.target.checked })} />
          Include this sheet in retrieval
        </label>
        <label className="sv-field">
          <span className="sv-label">Table name</span>
          <input className="sv-input" value={sheet.table_name} disabled={locked || sheet.excluded} onChange={(event) => onChange({ ...sheet, table_name: event.target.value })} />
        </label>
        <label className="sv-field">
          <span className="sv-label">Header rows</span>
          <input className="sv-input" inputMode="numeric" value={sheet.header_rows.join(", ")} disabled={locked || sheet.excluded} onChange={(event) => onChange({ ...sheet, header_rows: headerRows(event.target.value) })} />
          <small className="text-secondary">Use up to three row numbers, for example 3, 4 for grouped headers. Candidates: {sheet.header_candidates.join(", ") || "none"}.</small>
        </label>
        <label className="sv-field">
          <span className="sv-label">Table description</span>
          <textarea className="sv-input" value={sheet.description} disabled={locked || sheet.excluded} onChange={(event) => onChange({ ...sheet, description: event.target.value })} />
        </label>
        {!sheet.excluded ? sheet.columns.map((column, columnIndex) => (
          <fieldset className="spreadsheet-review-column" key={column.index} disabled={locked}>
            <legend>Column {column.index + 1}</legend>
            <label className="sv-field">
              <span className="sv-label">Name</span>
              <input className="sv-input" value={column.name} onChange={(event) => onChange({ ...sheet, columns: sheet.columns.map((value, index) => index === columnIndex ? { ...value, name: event.target.value } : value) })} />
            </label>
            <label className="sv-field">
              <span className="sv-label">Description</span>
              <textarea className="sv-input" value={column.description} onChange={(event) => onChange({ ...sheet, columns: sheet.columns.map((value, index) => index === columnIndex ? { ...value, description: event.target.value } : value) })} />
            </label>
            <label className="sv-field">
              <span className="sv-label">Aliases</span>
              <input className="sv-input" value={column.aliases.join(", ")} onChange={(event) => onChange({ ...sheet, columns: sheet.columns.map((value, index) => index === columnIndex ? { ...value, aliases: event.target.value.split(",").map((alias) => alias.trim()).filter(Boolean).slice(0, 5) } : value) })} />
            </label>
          </fieldset>
        )) : null}
      </div>
    </details>
  );
}

function headerRows(value: string) {
  return Array.from(new Set(value.split(",").map((part) => Number(part.trim())).filter((row) => Number.isInteger(row) && row > 0))).sort((a, b) => a - b).slice(0, 3);
}
