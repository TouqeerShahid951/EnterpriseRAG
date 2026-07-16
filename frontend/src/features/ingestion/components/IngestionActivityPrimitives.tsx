import { Skeleton } from "@/components/layout/Common";
import { labelize } from "@/features/ingestion/components/IngestionJobTable";

export function FilterSelect({ helper, label, onChange, options, value }: { helper?: string; label: string; onChange: (value: string) => void; options: string[]; value: string }) {
  return (
    <label className="sv-field">
      <span className="sv-label">{label}</span>
      <select className="sv-select" value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => <option key={option || "all"} value={option}>{option ? labelize(option) : `All ${label}`}</option>)}
      </select>
      {helper ? <small className="text-secondary">{helper}</small> : null}
    </label>
  );
}

export function JobSkeleton() {
  return <div className="grid gap-2 p-4">{Array.from({ length: 5 }, (_, index) => <div className="knowledge-skeleton-row" key={index} />)}</div>;
}

export function JobMetric({ label, loading, tone, value }: { label: string; loading: boolean; tone?: "success"; value: number }) {
  return (
    <div className={tone === "success" ? "knowledge-context-metric knowledge-context-metric-success" : "knowledge-context-metric"}>
      <span>{label}</span>
      {loading ? <Skeleton className="mt-1 h-6 w-12" /> : <strong>{value}</strong>}
    </div>
  );
}
