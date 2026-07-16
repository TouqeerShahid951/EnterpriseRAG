import type { ConnectorReviewTab } from "@/features/connectors/utils/connectorPanelUtils";

const connectorReviewTabs: Array<{ id: ConnectorReviewTab; label: string }> = [
  { id: "summary", label: "Summary" },
  { id: "tables", label: "Tables & Columns" },
  { id: "joins", label: "Joins" },
  { id: "access", label: "Access" },
  { id: "raw_schema", label: "Raw Schema" },
];

export function ConnectorReviewTabs({ onChange, value }: ConnectorReviewTabsProps) {
  return (
    <div className="knowledge-inspector-tabs" role="tablist" aria-label="Database access review sections" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(7rem, 1fr))" }}>
      {connectorReviewTabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={value === tab.id}
          className={value === tab.id ? "knowledge-inspector-tab-active" : "knowledge-inspector-tab"}
          onClick={() => onChange(tab.id)}
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
  onChange: (tab: ConnectorReviewTab) => void;
  value: ConnectorReviewTab;
};

export type SchemaReviewMetricProps = {
  label: string;
  value: string;
};
