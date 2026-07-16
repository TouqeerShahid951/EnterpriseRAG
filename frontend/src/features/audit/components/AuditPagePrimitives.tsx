import type { JSX } from "react";
import { Skeleton } from "@/components/layout/Common";
import { auditCategoryLabel } from "@/features/audit/utils/audit";

export function AuditMetric({ icon, label, loading, value }: { icon: JSX.Element; label: string; loading: boolean; value: number }) {
  return (
    <div className="audit-metric" aria-busy={loading}>
      <span>{icon}</span>
      <div>
        <p>{label}</p>
        {loading ? <Skeleton className="mt-1 h-4 w-10" /> : <strong>{value}</strong>}
      </div>
    </div>
  );
}

export function AuditSelect({ label, onChange, options, value }: { label: string; onChange: (value: string) => void; options: string[]; value: string }) {
  return (
    <label className="sv-field">
      <span className="sv-label">{label}</span>
      <select className="sv-select" value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">All {label}</option>
        {options.map((option) => <option key={option} value={option}>{option.startsWith("/") ? option : auditCategoryLabel(option)}</option>)}
      </select>
    </label>
  );
}

export function AuditSkeleton() {
  return <div className="grid gap-2 p-4">{Array.from({ length: 7 }, (_, index) => <div className="knowledge-skeleton-row" key={index} />)}</div>;
}
