import { useRef, useState, type ReactNode } from "react";
import { Filter } from "lucide-react";

type Filters = { days: number; outcome: string; onChange: (patch: { days?: number; outcome?: string }) => void };

const outcomeOptions = [
  ["", "All outcomes"], ["complete", "Complete"], ["partial", "Partial"],
  ["clarification", "Clarification"], ["abstained", "Abstained"], ["system_error", "System error"],
  ["access_denied", "Access denied"], ["cancelled", "Cancelled"], ["interrupted", "Interrupted"],
];

export function AnalyticsPeriodOutcomeFilters({ prefix, days, outcome, onChange }: Filters & { prefix: string }) {
  return <>
    <label htmlFor={`${prefix}-outcome`}>Outcome</label>
    <select id={`${prefix}-outcome`} className="sv-action-secondary" value={outcome} onChange={(event) => onChange({ outcome: event.target.value })}>
      {outcomeOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
    </select>
    <label htmlFor={`${prefix}-period`}>Period</label>
    <select id={`${prefix}-period`} className="sv-action-secondary" value={days} onChange={(event) => onChange({ days: Number(event.target.value) })}>
      <option value={1}>Last 24 hours</option><option value={7}>Last 7 days</option><option value={30}>Last 30 days</option>
    </select>
  </>;
}

export function AnalyticsChartPanel({ children, subtitle, title, filters }: { children: ReactNode; subtitle: string; title: string; filters: Filters }) {
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const headingId = `chart-${title.toLowerCase().replace(/ /g, "-")}`;
  return <section className="sv-panel analytics-panel analytics-chart-panel" aria-labelledby={headingId} onKeyDown={(event) => {
    if (event.key === "Escape" && open) { event.stopPropagation(); setOpen(false); button.current?.focus(); }
  }}>
    <header className="analytics-panel-heading">
      <div><h2 id={headingId}>{title}</h2><p>{subtitle}</p></div>
      <button ref={button} type="button" className="sv-action-secondary analytics-chart-filter" aria-label={`Filter ${title}`} aria-expanded={open} aria-controls={`${headingId}-filters`} onClick={() => setOpen(!open)}><Filter size={16} aria-hidden="true" /> Filters</button>
    </header>
    {open ? <fieldset id={`${headingId}-filters`} className="analytics-chart-filters">
      <legend className="sr-only">{title} filters</legend>
      <div className="analytics-toolbar-actions"><AnalyticsPeriodOutcomeFilters prefix={headingId} {...filters} /></div>
      <p className="analytics-caption">Filters apply to all analytics charts and the query list. Select a chart bucket to inspect its executions.</p>
    </fieldset> : null}
    {children}
  </section>;
}
