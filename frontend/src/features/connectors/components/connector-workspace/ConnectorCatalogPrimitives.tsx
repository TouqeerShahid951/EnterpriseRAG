import type { KeyboardEvent } from "react";

import type { ConnectorReviewTab } from "@/features/connectors/utils/connectorPanelUtils";

const connectorReviewTabs: Array<{ id: ConnectorReviewTab; label: string }> = [
  { id: "summary", label: "Summary" },
  { id: "tables", label: "Tables & Columns" },
  { id: "joins", label: "Joins" },
  { id: "access", label: "Access" },
  { id: "raw_schema", label: "Raw Schema" },
];

export function ConnectorReviewTabs({ idPrefix, onChange, value }: ConnectorReviewTabsProps) {
  function handleKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    let nextIndex: number | null = null;
    if (event.key === "ArrowRight") nextIndex = (index + 1) % connectorReviewTabs.length;
    if (event.key === "ArrowLeft") nextIndex = (index - 1 + connectorReviewTabs.length) % connectorReviewTabs.length;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = connectorReviewTabs.length - 1;
    if (nextIndex === null) return;

    event.preventDefault();
    const nextTab = connectorReviewTabs[nextIndex];
    onChange(nextTab.id);
    event.currentTarget.ownerDocument.getElementById(`${idPrefix}-tab-${nextTab.id}`)?.focus();
  }

  return (
    <div className="knowledge-inspector-tabs" role="tablist" aria-label="Database access review sections" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(7rem, 1fr))" }}>
      {connectorReviewTabs.map((tab, index) => (
        <button
          key={tab.id}
          id={`${idPrefix}-tab-${tab.id}`}
          type="button"
          role="tab"
          aria-controls={`${idPrefix}-panel-${tab.id}`}
          aria-selected={value === tab.id}
          className={value === tab.id ? "knowledge-inspector-tab-active" : "knowledge-inspector-tab"}
          onClick={() => onChange(tab.id)}
          onKeyDown={(event) => handleKeyDown(event, index)}
          tabIndex={value === tab.id ? 0 : -1}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

export function SchemaReviewMetric({ label, value }: SchemaReviewMetricProps) {
  return (
    <div className="rounded-md border border-surface-border bg-surface px-3 py-2">
      <dt className="text-label-md font-bold uppercase tracking-wide text-secondary">{label}</dt>
      <dd className="mt-1 text-body-lg font-extrabold text-on-surface">{value}</dd>
    </div>
  );
}

export function SchemaReviewStat({ label, value }: SchemaReviewMetricProps) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-surface-border py-1.5 last:border-b-0">
      <dt className="text-secondary">{label}</dt>
      <dd className="font-extrabold text-on-surface">{value}</dd>
    </div>
  );
}

export type ConnectorReviewTabsProps = {
  idPrefix: string;
  onChange: (tab: ConnectorReviewTab) => void;
  value: ConnectorReviewTab;
};

export type SchemaReviewMetricProps = {
  label: string;
  value: string;
};
