import type { DocumentOverview } from "@/types/api";
import { UsageRing } from "@/components/charts/UsageRing";

export function CorpusReadiness({ data, loading }: { data?: DocumentOverview; loading: boolean }) {
  const spaces = [...(data?.spaces ?? [])].sort((a, b) => b.library_documents - a.library_documents).slice(0, 5);
  return <div className="overview-corpus-layout">
    <section className="sv-panel overview-panel">
      <header className="overview-panel-heading"><div><h2>Retrieval readiness</h2><p>Current documents ready to query</p></div></header>
      {data ? <div className="overview-readiness">
        <UsageRing value={data.current_versions > 0 ? 100 * data.indexed_current / data.current_versions : null} label="Indexed current documents" detail="indexed" tone="success" />
        <div className="overview-readiness-copy"><p><strong>{data.indexed_current.toLocaleString()}</strong> of {data.current_versions.toLocaleString()} current documents indexed</p>
          <dl className="overview-readiness-stats">
            <div><dt>Processing</dt><dd>{data.processing_current}</dd></div>
            <div><dt>Needs attention</dt><dd>{data.needs_attention}</dd></div>
            <div><dt>Failed</dt><dd>{data.failed_current}</dd></div>
            <div><dt>Expiring in 30 days</dt><dd>{data.expiring_soon_current}</dd></div>
          </dl>
          {data.current_versions === 0 ? <p className="overview-caption">Add documents to measure readiness.</p> : null}
        </div>
      </div> : <p className="overview-empty">{loading ? "Loading readiness…" : "Readiness unavailable"}</p>}
    </section>
    <section className="sv-panel overview-panel">
      <header className="overview-panel-heading"><div><h2>Top Knowledge Spaces</h2><p>Ranked by visible library volume</p></div><span className="overview-status">{data?.spaces.length ?? "—"} spaces</span></header>
      <div className="overview-space-table"><table><thead><tr><th scope="col">Knowledge Space</th><th scope="col">Documents</th><th scope="col">Attention</th></tr></thead><tbody>
        {spaces.map((space, index) => <tr key={space.group_path}>
          <th scope="row"><span className="overview-rank">{index + 1}</span><span className="overview-space-name">{space.group_path}</span></th>
          <td><strong>{space.library_documents.toLocaleString()}</strong><svg viewBox="0 0 100 4" aria-hidden="true" preserveAspectRatio="none"><rect className="overview-bar-track" width="100" height="4" rx="2" /><rect className="overview-bar-fill" width={100 * space.library_documents / Math.max(spaces[0].library_documents, 1)} height="4" rx="2" /></svg></td>
          <td><span className="overview-status" data-tone={space.failed_current + space.review_current + space.unknown_current > 0 ? "warning" : "neutral"}>{space.failed_current + space.review_current + space.unknown_current}</span></td>
        </tr>)}
      </tbody></table></div>
      {!spaces.length ? <p className="overview-empty">{loading ? "Loading spaces…" : !data ? "Spaces unavailable" : "No visible library documents yet."}</p> : null}
    </section>
  </div>;
}
