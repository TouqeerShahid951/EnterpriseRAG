import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ingestJobsApi } from "@/lib/api/contracts";
import { InlineMessage } from "@/components/layout/Common";
import { RecentActivityList } from "./DocumentOverviewPanels";
import type { NavigateOptions, RouteId } from "@/routes/routes";

/** Keep confirmed recovery outcomes visible after documents leave a failure filter. */
export function DocumentRecoveryActivity({ onNavigate }: { onNavigate: (route: RouteId, options?: NavigateOptions) => void }) {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["ingest-jobs", "document-recovery"],
    queryFn: () => ingestJobsApi.list({ origin: "reingest", limit: 5 }),
    refetchInterval: (result) => result.state.data?.items.some((job) => ["queued", "scheduled", "processing", "human_review"].includes(job.status)) ? 3000 : 15000,
    staleTime: 2000, retry: false,
  });
  const states = query.data?.items.map((job) => `${job.job_id}:${job.status}`).join("|");
  useEffect(() => {
    if (states) void client.invalidateQueries({ queryKey: ["documents"] });
  }, [client, states]);
  if (!query.isError && !query.data?.items.length) return null;
  return <details className="sv-panel mt-4" aria-label="Recent document recovery">
    <summary className="cursor-pointer p-4 text-title-md">Recent recovery attempts · {query.data?.items.length ?? 0} latest · {query.data?.items.filter((job) => ["queued", "scheduled", "processing"].includes(job.status)).length ?? 0} processing · {query.data?.items.filter((job) => job.status === "failed").length ?? 0} failed</summary>
    <div className="flex flex-wrap items-start justify-between gap-2 p-4">
      <div><h2 className="sv-section-title">Recent recovery attempts</h2><p className="text-body-md text-secondary">Latest 5 reingestion attempts across your visible documents. Queued does not mean resolved.</p></div>
      <button className="sv-action-secondary" type="button" onClick={() => onNavigate("ingestion-jobs", { search: "?origin=reingest" })}>Full recovery history</button>
    </div>
    {query.isError ? <InlineMessage tone="warning">Recovery status could not be refreshed. <button type="button" onClick={() => void query.refetch()}>Retry refresh</button></InlineMessage> : null}
    <RecentActivityList isLoading={query.isLoading} jobs={query.data?.items ?? []} onNavigate={onNavigate} />
  </details>;
}
