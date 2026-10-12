import { useQuery } from "@tanstack/react-query";
import { Activity, Clock3 } from "lucide-react";
import { useState } from "react";
import { auditApi } from "@/lib/api/contracts";
import { InlineMessage, Skeleton } from "@/components/layout/Common";

export function WorkspaceActivity() {
  const [days, setDays] = useState(7);
  const query = useQuery({
    queryKey: ["audit-log", "overview", days],
    queryFn: () => auditApi.list({ created_from: new Date(Date.now() - days * 86400000).toISOString(), limit: 6 }),
    refetchInterval: 30000, retry: false,
  });
  const summary = query.data?.summary;
  const categories = Object.entries(summary?.category_counts ?? {}).sort((a, b) => b[1] - a[1]);
  return <div className="overview-activity-layout">
    <section className="sv-panel overview-panel" aria-labelledby="activity-title">
      <header className="overview-panel-heading">
        <div><h2 id="activity-title">System activity</h2><p>Recorded events by category</p></div>
        <select className="sv-action-secondary" aria-label="Activity period" value={days} onChange={(event) => setDays(Number(event.target.value))}><option value={7}>Last 7 days</option><option value={30}>Last 30 days</option></select>
      </header>
      {query.isError ? <InlineMessage tone="warning">Activity could not be refreshed. <button type="button" onClick={() => void query.refetch()}>Retry</button></InlineMessage> : null}
      {query.isLoading ? <Skeleton className="h-56 w-full" /> : null}
      {summary ? <>
        <div className="overview-activity-total"><strong>{summary.total.toLocaleString()}</strong><span>events in {days} days<br /><small>{summary.actor_count} distinct actors</small></span></div>
        <div className="overview-bar-chart" aria-label="Activity category breakdown">
          {categories.map(([label, count], index) => <div className="overview-bar-row" key={label}>
            <div className="overview-bar-label"><span>{label.replace(/_/g, " ")}</span><strong>{count.toLocaleString()} <small>{summary.total > 0 ? Math.round(count / summary.total * 100) : 0}%</small></strong></div>
            <svg viewBox="0 0 400 12" preserveAspectRatio="none" role="img" aria-label={`${label}: ${count} of ${summary.total} events`}>
              <rect className="overview-bar-track" width="400" height="12" rx="4" />
              <rect className={`overview-bar-fill overview-series-${index % 4}`} width={400 * count / Math.max(summary.total, 1)} height="12" rx="4" />
            </svg>
          </div>)}
        </div>
        {summary.total === 0 ? <p className="overview-empty">No recorded activity in this period.</p> : null}
        <p className="overview-panel-footnote">Authorized audit scope · share of all recorded events</p>
      </> : null}
    </section>
    <section className="sv-panel overview-panel" aria-labelledby="recent-title">
      <header className="overview-panel-heading"><div><h2 id="recent-title">Recent activity</h2><p>Latest events in the selected period</p></div><Clock3 size={18} aria-hidden="true" /></header>
      {query.isLoading ? <Skeleton className="h-56 w-full" /> : null}
      <ol className="overview-event-list">{query.data?.items.map((event) => <li key={event.id}>
        <span className="overview-event-icon"><Activity size={15} aria-hidden="true" /></span>
        <div><p className="overview-event-title">{event.event_type.replace(/\./g, " · ").replace(/_/g, " ")}</p>
          <p className="overview-caption">{event.target_document_title ?? event.actor_email ?? event.target_type ?? "System"}</p></div>
        {event.created_at ? <time title={new Date(event.created_at).toLocaleString()} dateTime={event.created_at}>{new Date(event.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })}<br />{new Date(event.created_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}</time> : null}
      </li>)}</ol>
      {!query.isLoading && !query.data?.items.length ? <p className="overview-empty">{query.isError ? "Recent activity unavailable." : "No recent events in this period."}</p> : null}
    </section>
  </div>;
}
