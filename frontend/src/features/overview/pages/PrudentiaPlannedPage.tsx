import { useQuery } from "@tanstack/react-query";
import { Activity, ArrowRight, FileText, Search, Upload, Users } from "lucide-react";

import { adminApi, reviewApi } from "@/lib/api/contracts";
import { accountTypeLabel, isGlobalAdmin } from "@/lib/auth/authz";
import { InlineMessage, Skeleton } from "@/components/layout/Common";
import { PrudentiaBasicPage } from "@/components/layout/PrudentiaWorkspace";
import { canAccessRoute, type RouteId } from "@/routes/routes";
import type { Document, User as AuthUser } from "@/types/api";
import { errorMessage } from "@/lib/utils/format";
import { countGroups } from "@/lib/utils/groups";

export function PrudentiaOverviewPage({ documents, documentsLoading, onLogout, onNavigate, user }: OverviewProps) {
  const isAdmin = isGlobalAdmin(user);
  const canReview = canAccessRoute(user, "review");
  const role = accountTypeLabel(user.account_type);
  const canQuery = canAccessRoute(user, "chat");
  const canUpload = canAccessRoute(user, "upload");
  const currentCount = documents.filter((doc) => doc.is_current).length;
  const supersededCount = documents.length - currentCount;

  const groupsQuery = useQuery({ queryKey: ["admin", "groups"], queryFn: adminApi.listGroups, enabled: isAdmin, retry: false });
  const usersQuery = useQuery({ queryKey: ["admin", "users"], queryFn: adminApi.listUsers, enabled: isAdmin, retry: false });
  const reviewQuery = useQuery({ queryKey: ["review-queue"], queryFn: reviewApi.list, enabled: canReview, staleTime: 4000, retry: false });

  const spaceCount = isAdmin ? (groupsQuery.data ? countGroups(groupsQuery.data.items) : null) : user.group_paths.length;
  const userCount = usersQuery.data?.total ?? usersQuery.data?.items.length ?? null;
  const pendingReviews = reviewQuery.data?.items.filter((item) => item.status === "pending").length ?? null;

  const actions = [
    { icon: <Search size={18} />, label: "Query Intelligence", description: "Ask against indexed evidence with source citations and trace context.", onClick: () => onNavigate("chat"), route: "chat" },
    { icon: <Upload size={18} />, label: "Document Intake", description: "Add files and track folder or upload activity through indexing.", onClick: () => onNavigate("upload"), route: "upload" },
    { icon: <FileText size={18} />, label: "Document Library", description: "Manage spaces, indexed documents, versions, and repository metadata.", onClick: () => onNavigate("document-overview"), route: "document-overview" },
    { icon: <Activity size={18} />, label: "Ingestion Health", description: "Review pipeline status, stage distribution, failures, and scheduled-source health.", onClick: () => onNavigate("ingestion-health"), route: "ingestion-health" },
    { icon: <Users size={18} />, label: "User Management", description: "Create users and assign Knowledge Space access.", onClick: () => onNavigate("access"), route: "access" },
  ] satisfies OverviewActionProps[];
  const visibleActions = actions.filter((action) => canAccessRoute(user, action.route));
  const priorityRoute = !documentsLoading && currentCount === 0 && canUpload
    ? "upload"
    : canQuery
      ? "chat"
      : visibleActions[0]?.route;
  const priorityAction = visibleActions.find((action) => action.route === priorityRoute) ?? visibleActions[0] ?? null;
  const supportingActions = visibleActions.filter((action) => action.route !== priorityAction?.route);

  return (
    <PrudentiaBasicPage activeRoute="overview" onLogout={onLogout} onNavigate={onNavigate} title="Workspace Summary" subtitle="High-level corpus, access, and review facts with shortcuts into focused operational workspaces." user={user}>
      <div className="space-y-6">
        <section className="sv-panel p-5">
          <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
            <div>
              <p className="sv-eyebrow">Control Plane</p>
              <h2 className="mt-2 text-headline-sm text-on-surface">Enterprise RAG workspace</h2>
              <p className="mt-2 max-w-2xl text-body-md text-on-surface-variant">
                Review the active corpus and access posture, then open the focused workspace for the operation you need.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              {canQuery ? (
                <button type="button" onClick={() => onNavigate("chat")} className="sv-action-primary">
                  <Search size={16} /> Ask
                </button>
              ) : null}
              {canUpload ? (
                <button type="button" onClick={() => onNavigate("upload")} className="sv-action-secondary">
                  <Upload size={16} /> Upload
                </button>
              ) : null}
            </div>
          </div>
          <div className="workspace-overview-metrics mt-6 grid md:grid-cols-2 xl:grid-cols-4">
            <Metric label="Current documents" value={String(currentCount)} detail={`${supersededCount} superseded`} loading={documentsLoading} />
            <Metric label="Knowledge Spaces" value={valueOrUnavailable(spaceCount)} detail={isAdmin ? "Workspace hierarchy" : user.group_paths[0] ?? "No space assigned"} loading={isAdmin && groupsQuery.isLoading} />
            <Metric label="Users" value={isAdmin ? valueOrUnavailable(userCount) : role} detail={isAdmin ? "Provisioned accounts" : `Permission v${user.permission_version}`} loading={isAdmin && usersQuery.isLoading} />
            <Metric label="Review Queue" value={canReview ? valueOrUnavailable(pendingReviews) : "Restricted"} detail={canReview ? "Pending review items" : "Reviewer access required"} loading={canReview && reviewQuery.isLoading} />
          </div>
          {groupsQuery.isError ? <InlineMessage tone="error">{errorMessage(groupsQuery.error, "Unable to load Knowledge Space count.")}</InlineMessage> : null}
          {usersQuery.isError ? <InlineMessage tone="error">{errorMessage(usersQuery.error, "Unable to load user count.")}</InlineMessage> : null}
          {reviewQuery.isError ? <InlineMessage tone="warning">{errorMessage(reviewQuery.error, "Unable to load review queue.")}</InlineMessage> : null}
        </section>

        {priorityAction ? (
          <section className="workspace-overview-actions" aria-labelledby="workspace-actions-title">
            <div className="mb-4 flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <p className="sv-eyebrow">Operational workspaces</p>
                <h2 id="workspace-actions-title" className="mt-2 text-headline-sm text-on-surface">Choose the next task</h2>
              </div>
              <p className="max-w-xl text-body-md text-on-surface-variant sm:text-right">Each workspace stays focused on one stage of the evidence lifecycle.</p>
            </div>
            <div className="workspace-overview-action-layout grid gap-4 lg:grid-cols-[minmax(0,1.15fr)_minmax(20rem,0.85fr)]">
              <OverviewAction {...priorityAction} priority />
              {supportingActions.length ? (
                <div className="sv-panel workspace-overview-action-list overflow-hidden" aria-label="More operational workspaces">
                  {supportingActions.map((action) => <OverviewAction key={action.label} {...action} />)}
                </div>
              ) : null}
            </div>
          </section>
        ) : null}
      </div>
    </PrudentiaBasicPage>
  );
}

function OverviewAction({ description, icon, label, onClick, priority = false }: OverviewActionProps & { priority?: boolean }) {
  if (priority) {
    return (
      <button
        type="button"
        onClick={onClick}
        className="sv-card workspace-overview-action workspace-overview-action-priority flex min-h-56 flex-col p-6 text-left transition-colors hover:bg-surface-container-high"
        data-cursor-glow
        aria-label={`Open ${label}`}
      >
        <span className="mb-5 flex h-11 w-11 items-center justify-center rounded-lg border border-primary/20 bg-primary/10 text-primary">{icon}</span>
        <span className="sv-eyebrow">{label === "Document Intake" ? "Build the corpus" : "Primary workflow"}</span>
        <strong className="mt-2 block text-headline-md text-on-surface">{label}</strong>
        <span className="mt-2 block max-w-xl text-body-md text-on-surface-variant">{description}</span>
        <span className="mt-auto flex items-center gap-2 pt-6 text-label-md font-semibold text-primary">Open workspace <ArrowRight size={16} aria-hidden="true" /></span>
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={onClick}
      className="workspace-overview-action workspace-overview-action-supporting flex w-full items-start gap-4 border-b border-surface-border p-4 text-left transition-colors last:border-b-0 hover:bg-surface-container-high"
      aria-label={`Open ${label}`}
    >
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-primary/20 bg-primary/10 text-primary">{icon}</span>
      <span className="min-w-0 flex-1">
        <strong className="block text-title-md text-on-surface">{label}</strong>
        <span className="mt-1 block text-body-md text-on-surface-variant">{description}</span>
      </span>
      <ArrowRight className="mt-1 shrink-0 text-secondary" size={16} aria-hidden="true" />
    </button>
  );
}

function Metric({ detail, label, loading, value }: MetricProps) {
  return (
    <div className="sv-metric" aria-busy={loading} data-cursor-glow>
      <p className="sv-metadata">{label}</p>
      {loading ? (
        <>
          <span className="sr-only">Loading {label.toLowerCase()}</span>
          <Skeleton className="mt-2 h-7 w-16" />
          <Skeleton className="mt-2 h-3 w-28" />
        </>
      ) : (
        <>
          <p className="sv-metric-value mt-2">{value}</p>
          <p className="mt-1 truncate text-label-md text-secondary">{detail}</p>
        </>
      )}
    </div>
  );
}

function valueOrUnavailable(value: string | number | null): string {
  if (value === null || value === undefined || value === "") return "Unavailable";
  return String(value);
}

type SharedProps = {
  onLogout: () => void;
  onNavigate: (route: RouteId) => void;
  user: AuthUser;
};

type OverviewProps = SharedProps & {
  documents: Document[];
  documentsLoading: boolean;
};

type OverviewActionProps = {
  description: string;
  icon: JSX.Element;
  label: string;
  onClick: () => void;
  route: RouteId;
};

type MetricProps = {
  detail: string;
  label: string;
  loading: boolean;
  value: string;
};
