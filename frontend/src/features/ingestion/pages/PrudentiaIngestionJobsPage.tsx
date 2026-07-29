import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, FileClock, FileSearch, Search, Upload } from "lucide-react";

import { adminApi, documentsApi, ingestJobsApi } from "@/lib/api/contracts";
import { canManageSpaces, canUpload, canViewSpaceMetadata } from "@/lib/auth/authz";
import { useToast } from "@/components/feedback/ToastProvider";
import { InlineMessage } from "@/components/layout/Common";
import { PrudentiaWorkspace } from "@/components/layout/PrudentiaWorkspace";
import type { RouteId } from "@/routes/routes";
import type { GraphEnrichmentTask } from "@/features/upload/state/uploadJobProgress";
import type { IngestJob, IngestJobOrigin, UploadJobState, User as AuthUser } from "@/types/api";
import { errorMessage } from "@/lib/utils/format";
import { flattenGroups, userSpacesFromPaths } from "@/lib/utils/groups";
import { isActiveJob, JobTable, retryRequestForJob } from "@/features/ingestion/components/IngestionJobTable";
import { FilterSelect, JobMetric, JobSkeleton } from "@/features/ingestion/components/IngestionActivityPrimitives";
import {
  initialActivityOffsetFromUrl,
  initialActivityStringParam,
  initialJobOriginFromUrl,
  initialJobStatusFromUrl,
  syncActivityUrl,
  useDebouncedText,
} from "@/features/ingestion/state/ingestionActivityUrl";


const PAGE_SIZE = 25;

export function PrudentiaIngestionJobsPage({ onLogout, onNavigate, user }: Props) {
  const [search, setSearch] = useState(() => initialActivityStringParam("job_q") || initialActivityStringParam("search"));
  const [status, setStatus] = useState<UploadJobState | "">(() => initialJobStatusFromUrl());
  const [origin, setOrigin] = useState<IngestJobOrigin | "">(() => initialJobOriginFromUrl());
  const [groupPath, setGroupPath] = useState(() => initialActivityStringParam("space"));
  const [createdFrom, setCreatedFrom] = useState(() => initialActivityStringParam("created_from"));
  const [createdTo, setCreatedTo] = useState(() => initialActivityStringParam("created_to"));
  const [offset, setOffset] = useState(() => initialActivityOffsetFromUrl());
  const debouncedSearch = useDebouncedText(search, 300);
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const canLoadDirectory = canManageSpaces(user) || canViewSpaceMetadata(user);
  const summaryRequest = {
    group_path: groupPath || undefined,
    created_from: createdFrom ? `${createdFrom}T00:00:00Z` : undefined,
    created_to: createdTo ? `${createdTo}T23:59:59Z` : undefined,
  };
  const hasSummaryFilters = Boolean(summaryRequest.group_path || summaryRequest.created_from || summaryRequest.created_to);
  const groupsQuery = useQuery({ queryKey: ["admin", "groups"], queryFn: adminApi.listGroups, enabled: canLoadDirectory, retry: false });
  const spaceOptions = useMemo(
    () => (canLoadDirectory ? flattenGroups(groupsQuery.data?.items ?? []) : userSpacesFromPaths(user.group_paths)),
    [canLoadDirectory, groupsQuery.data?.items, user.group_paths],
  );
  const jobsQuery = useQuery({
    queryKey: ["ingest-jobs", "list", debouncedSearch, status, origin, groupPath, createdFrom, createdTo, offset],
    queryFn: () =>
      ingestJobsApi.list({
        search: debouncedSearch,
        status,
        origin,
        group_path: groupPath || undefined,
        created_from: createdFrom ? `${createdFrom}T00:00:00Z` : undefined,
        created_to: createdTo ? `${createdTo}T23:59:59Z` : undefined,
        limit: PAGE_SIZE,
        offset,
      }),
    refetchInterval: (query) => query.state.data?.items.some((job) => isActiveJob(job.status)) ? 2500 : false,
    retry: false,
  });
  const summaryQuery = useQuery({
    queryKey: hasSummaryFilters ? ["ingest-jobs", "summary", summaryRequest] : ["ingest-jobs", "summary"],
    queryFn: () => ingestJobsApi.summary(summaryRequest),
    refetchInterval: (query) => query.state.data?.active ? 2500 : false,
    staleTime: 4000,
    retry: false,
  });
  const cancelMutation = useMutation({
    mutationFn: (jobId: string) => ingestJobsApi.cancel(jobId),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["ingest-jobs"] });
      void queryClient.invalidateQueries({ queryKey: ["upload"] });
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["review-queue"] });
    },
  });
  const reingestMutation = useMutation({
    mutationFn: (job: IngestJob) => documentsApi.reingest(job.document_id, retryRequestForJob(job)),
    onSuccess: async (response, job) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["ingest-jobs"] }),
        queryClient.invalidateQueries({ queryKey: ["upload"] }),
        queryClient.invalidateQueries({ queryKey: ["documents"] }),
        queryClient.invalidateQueries({ queryKey: ["audit-log"] }),
      ]);
      notify({
        title: job.status === "complete" ? "Reingestion queued" : "Retry queued",
        description: `${job.document_title} queued as job ${response.job_id}.`,
        tone: "success",
      });
    },
    onError: (error) => notify({
      title: "Retry failed",
      description: errorMessage(error, "Unable to queue document reingestion."),
      tone: "error",
    }),
  });
  const graphEnrichmentMutation = useMutation({
    mutationFn: (job: IngestJob) => documentsApi.enrichGraph(job.document_id),
    onSuccess: async (response, job) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["ingest-jobs", "graphrag-status"] }),
        queryClient.invalidateQueries({ queryKey: ["audit-log"] }),
      ]);
      notify({
        title: "Graph enrichment queued",
        description: `${job.document_title} queued as graph task for job ${response.job_id}.`,
        tone: "success",
      });
    },
    onError: (error) => notify({
      title: "Graph enrichment not queued",
      description: errorMessage(error, "Unable to queue graph enrichment."),
      tone: "error",
    }),
  });
  const graphCancelMutation = useMutation({
    mutationFn: ({ job, task }: { job: IngestJob; task: GraphEnrichmentTask }) =>
      ingestJobsApi.cancelGraphEnrichment(task.jobId ?? job.job_id, task.taskId),
    onSuccess: async (response, { job }) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["ingest-jobs", "graphrag-status"] }),
        queryClient.invalidateQueries({ queryKey: ["audit-log"] }),
      ]);
      notify({ title: "Graph enrichment cancelled", description: `${job.document_title}: ${response.message}`, tone: "success" });
    },
    onError: (error) => notify({
      title: "Graph enrichment not cancelled",
      description: errorMessage(error, "Unable to cancel graph enrichment."),
      tone: "error",
    }),
  });
  const items = jobsQuery.data?.items ?? [];
  const hasIndexedJobs = items.some((job) => job.status === "complete");
  const graphStatusQuery = useQuery({
    queryKey: ["ingest-jobs", "graphrag-status", "activity"],
    queryFn: ingestJobsApi.graphragStatus,
    enabled: hasIndexedJobs,
    refetchInterval: hasIndexedJobs ? 5000 : false,
    staleTime: 3000,
    retry: false,
  });
  const graphStatusError = graphStatusQuery.isError ? errorMessage(graphStatusQuery.error, "Unable to load graph enrichment status.") : null;
  const total = jobsQuery.data?.total ?? 0;
  const summary = summaryQuery.data;
  const firstItem = total === 0 ? 0 : offset + 1;
  const lastItem = Math.min(offset + items.length, total);

  useEffect(() => {
    syncActivityUrl({ createdFrom, createdTo, groupPath, offset, origin, search, status });
  }, [createdFrom, createdTo, groupPath, offset, origin, search, status]);

  function resetOffset<T>(setter: (value: T) => void, value: T) {
    setOffset(0);
    setter(value);
  }

  return (
    <PrudentiaWorkspace activeRoute="ingestion-jobs" onLogout={onLogout} onNavigate={onNavigate} user={user}>
      <main className="sv-page" id="main-content">
        <div className="sv-page-inner sv-page-inner-workbench max-w-none">
          <header className="sv-page-header">
            <div>
              <p className="sv-eyebrow">Document Intake</p>
              <h1 className="sv-page-title">Activity</h1>
              <p className="sv-page-subtitle">Track upload, folder, restore, and reingestion runs across your visible Knowledge Spaces.</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button type="button" onClick={() => onNavigate("document-overview")} className="sv-action-secondary">
                <FileSearch size={16} /> Overview
              </button>
              {canUpload(user) ? (
                <button type="button" onClick={() => onNavigate("upload")} className="sv-action-primary">
                  <Upload size={16} /> Add Files
                </button>
              ) : null}
            </div>
          </header>

          {summaryQuery.isError ? <InlineMessage tone="warning">{errorMessage(summaryQuery.error, "Unable to load activity summary.")}</InlineMessage> : null}
          <section className="sv-panel overflow-hidden">
            <div className="knowledge-job-metrics" aria-label="Ingestion job summary">
              <JobMetric label="Active" loading={summaryQuery.isLoading} value={summary?.active ?? 0} />
              <JobMetric label="Needs Review" loading={summaryQuery.isLoading} value={summary?.status_counts.human_review ?? 0} />
              <JobMetric label="Failed Runs" loading={summaryQuery.isLoading} value={summary?.status_counts.failed ?? 0} />
              <JobMetric label="Indexed" loading={summaryQuery.isLoading} value={summary?.status_counts.complete ?? 0} tone="success" />
              <JobMetric label="Total Runs" loading={summaryQuery.isLoading} value={summary?.total ?? 0} />
            </div>
          </section>

          <section className="sv-panel p-4">
            <div className="ingest-job-filters">
              <label className="ingest-job-search sv-field">
                <span className="sv-label">Search</span>
                <span className="knowledge-tree-search">
                  <Search size={16} aria-hidden="true" />
                  <input value={search} onChange={(event) => resetOffset(setSearch, event.target.value)} placeholder="Search document, job ID, or space..." />
                </span>
              </label>
              <FilterSelect label="Status" value={status} onChange={(value) => resetOffset(setStatus, value as UploadJobState | "")} options={["", "scheduled", "queued", "processing", "human_review", "cancelled", "failed", "complete"]} helper="Filter by current ingestion state." />
              <FilterSelect label="Origin" value={origin} onChange={(value) => resetOffset(setOrigin, value as IngestJobOrigin | "")} options={["", "upload", "folder", "connector", "reingest", "restore", "unknown"]} helper="Filter by how the job entered the queue." />
              <FilterSelect label="Knowledge Space" value={groupPath} onChange={(value) => resetOffset(setGroupPath, value)} options={["", ...spaceOptions.map((space) => space.path)]} helper="Limit activity to one retrieval space." />
              <label className="sv-field">
                <span className="sv-label">From</span>
                <input type="date" className="sv-input" value={createdFrom} onChange={(event) => resetOffset(setCreatedFrom, event.target.value)} />
                <small className="text-secondary">Show jobs created on or after this date.</small>
              </label>
              <label className="sv-field">
                <span className="sv-label">To</span>
                <input type="date" className="sv-input" value={createdTo} onChange={(event) => resetOffset(setCreatedTo, event.target.value)} />
                <small className="text-secondary">Show jobs created on or before this date.</small>
              </label>
            </div>
          </section>

          {jobsQuery.isError ? <InlineMessage tone="error">{errorMessage(jobsQuery.error, "Unable to load ingestion jobs.")}</InlineMessage> : null}
          {cancelMutation.isError ? <InlineMessage tone="error">{errorMessage(cancelMutation.error, "Unable to cancel ingestion job.")}</InlineMessage> : null}
          {reingestMutation.isError ? <InlineMessage tone="error">{errorMessage(reingestMutation.error, "Unable to queue document reingestion.")}</InlineMessage> : null}
          <section className="sv-panel overflow-hidden">
            <div className="ingest-job-list-header">
              <div>
                <h2 className="sv-section-title">Activity History</h2>
                <p>{jobsQuery.isLoading ? "Loading jobs" : `${firstItem}-${lastItem} of ${total}`}</p>
              </div>
              <div className="ingest-job-pagination">
                <button type="button" className="sv-action-secondary" disabled={offset === 0 || jobsQuery.isLoading} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
                  <ChevronLeft size={15} /> Previous
                </button>
                <button type="button" className="sv-action-secondary" disabled={offset + PAGE_SIZE >= total || jobsQuery.isLoading} onClick={() => setOffset(offset + PAGE_SIZE)}>
                  Next <ChevronRight size={15} />
                </button>
              </div>
            </div>
            {jobsQuery.isLoading ? <JobSkeleton /> : null}
            {!jobsQuery.isLoading && items.length === 0 ? (
              <div className="knowledge-empty-state">
                <FileClock size={22} />
                <h3>No ingestion jobs match these filters</h3>
                <p>Adjust the filters or upload a document to start a new job.</p>
              </div>
            ) : null}
            {!jobsQuery.isLoading && items.length > 0 ? (
              <JobTable
                cancelingJobId={cancelMutation.isPending ? cancelMutation.variables ?? null : null}
                cancellingGraphTaskId={graphCancelMutation.isPending ? graphCancelMutation.variables?.task.taskId ?? null : null}
                enrichingJobId={graphEnrichmentMutation.isPending ? graphEnrichmentMutation.variables?.job_id ?? null : null}
                graphStatus={graphStatusQuery.data}
                graphStatusError={graphStatusError}
                items={items}
                onCancelJob={(jobId) => cancelMutation.mutate(jobId)}
                onCancelGraph={(job, task) => graphCancelMutation.mutate({ job, task })}
                onEnrichGraph={(job) => graphEnrichmentMutation.mutate(job)}
                onReingestJob={(job) => reingestMutation.mutate(job)}
                reingestingDocumentId={reingestMutation.isPending ? reingestMutation.variables?.document_id ?? null : null}
                user={user}
              />
            ) : null}
          </section>
        </div>
      </main>
    </PrudentiaWorkspace>
  );
}
type Props = { onLogout: () => void; onNavigate: (route: RouteId) => void; user: AuthUser };
