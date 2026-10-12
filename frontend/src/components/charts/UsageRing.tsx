/** A percentage snapshot with a text equivalent; no implied historical trend. */
export function UsageRing({ value, label, detail, tone = "accent" }: { value: number | null; label: string; detail: string; tone?: "accent" | "success" | "warning" | "danger" }) {
  const percent = value === null ? null : Math.max(0, Math.min(100, value));
  return <div className="overview-ring" data-tone={tone}>
    <svg viewBox="0 0 120 120" aria-hidden="true">
      <circle className="overview-ring-track" cx="60" cy="60" r="50" />
      {percent !== null ? <circle className="overview-ring-value" cx="60" cy="60" r="50" pathLength="100" strokeDasharray={`${percent} 100`} transform="rotate(-90 60 60)" /> : null}
    </svg>
    <div className="overview-ring-label" role={percent === null ? undefined : "meter"} aria-label={percent === null ? undefined : label} aria-valuemin={percent === null ? undefined : 0} aria-valuemax={percent === null ? undefined : 100} aria-valuenow={percent ?? undefined}>
      <strong>{percent === null ? "—" : `${percent.toFixed(1)}%`}</strong><span>{percent === null ? "Unavailable" : detail}</span>
    </div>
  </div>;
}
