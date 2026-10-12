import { useQuery } from "@tanstack/react-query";
import { Activity, ArrowRight, FileText, FileCheck2, FolderOpen, Search, Upload, Users } from "lucide-react";
import type { MouseEvent } from "react";

import { adminApi, documentsApi, reviewApi } from "@/lib/api/contracts";
import { accountTypeLabel, isGlobalAdmin, isPlatformAdmin } from "@/lib/auth/authz";
import { InlineMessage, Skeleton } from "@/components/layout/Common";
import { PrudentiaBasicPage } from "@/components/layout/PrudentiaWorkspace";
import { canAccessRoute, routePaths, type RouteId } from "@/routes/routes";
import type { User as AuthUser } from "@/types/api";
import { errorMessage } from "@/lib/utils/format";
import { CorpusReadiness } from "@/features/overview/components/CorpusReadiness";
import { SystemResources } from "@/features/overview/components/SystemResources";
import { WorkspaceActivity } from "@/features/overview/components/WorkspaceActivity";
import { countGroups } from "@/lib/utils/groups";

export function PrudentiaOverviewPage({ onLogout, onNavigate, user }: SharedProps) {
  const isAdmin = isGlobalAdmin(user);
  const canReview = canAccessRoute(user, "review");
  const role = accountTypeLabel(user.account_type);
  const canQuery = canAccessRoute(user, "chat");
  const canUpload = canAccessRoute(user, "upload");
  const documentsQuery = useQuery({
    queryKey: ["documents", "overview"],
    queryFn: documentsApi.overview,
    refetchInterval: (query) => query.state.data?.processing_current ? 3000 : 15000,
    staleTime: 3000,
    retry: false,
  });
  const groupsQuery = useQuery({ queryKey: ["admin", "groups"], queryFn: adminApi.listGroups, enabled: isAdmin, retry: false });
  const usersQuery = useQuery({ queryKey: ["admin", "users"], queryFn: adminApi.listUsers, enabled: isAdmin, retry: false });
  const reviewQuery = useQuery({ queryKey: ["review-queue", "summary"], queryFn: reviewApi.summary, enabled: canReview, staleTime: 4000, retry: false });

  const currentCount = documentsQuery.data?.current_versions ?? null;
  const supersededCount = documentsQuery.data?.superseded_versions ?? null;
  const spaceCount = isAdmin ? (groupsQuery.data ? countGroups(groupsQuery.data.items) : null) : user.group_paths.length;
  const userCount = usersQuery.data?.total ?? usersQuery.data?.items.length ?? null;
  const pendingReviews = reviewQuery.data?.pending_document_count ?? null;

  const actions = [
    { icon: <Search size={18} />, label: "Query Intelligence", description: "Ask against indexed evidence with source citations and trace context.", route: "chat" },
    { icon: <Upload size={18} />, label: "Document Intake", description: "Add files and track folder or upload activity through indexing.", route: "upload" },
    { icon: <FileText size={18} />, label: "Document Library", description: "Manage spaces, indexed documents, versions, and repository metadata.", route: "document-overview" },
    { icon: <Activity size={18} />, label: "Pipeline Health", description: "Review pipeline status, stage distribution, failures, and scheduled-source health.", route: "ingestion-health" },
    { icon: <Users size={18} />, label: "User Management", description: "Create users and assign Knowledge Space access.", route: "access" },
  ] satisfies OverviewActionProps[];
  const visibleActions = actions.filter((action) => canAccessRoute(user, action.route));

  return (
    <PrudentiaBasicPage activeRoute="overview" onLogout={onLogout} onNavigate={onNavigate} title="System Overview" subtitle="Live corpus readiness, workspace activity, and system resource usage." user={user}>
      <div className="overview-dashboard">
        <div className="overview-toolbar">
          <p>Workspace at a glance <span>· Your authorized access scope</span></p>
          <div className="flex flex-wrap gap-2">
            {canQuery ? <a href={routePaths.chat} onClick={(event) => handleRouteClick(event, "chat", onNavigate)} className="sv-action-primary"><Search size={15} aria-hidden="true" /> Ask a question</a> : null}
            {canUpload ? <a href={routePaths.upload} onClick={(event) => handleRouteClick(event, "upload", onNavigate)} className="sv-action-secondary"><Upload size={15} aria-hidden="true" /> Upload</a> : null}
          </div>
        </div>
        <section className="overview-summary" aria-label="Workspace metrics">
          <Metric icon={<FileText size={20} />} label="Current documents" value={valueOrUnavailable(currentCount)} detail={supersededCount === null ? "Superseded unavailable" : `${supersededCount} superseded versions`} loading={documentsQuery.isLoading} />
          <Metric icon={<FolderOpen size={20} />} label="Knowledge Spaces" value={valueOrUnavailable(spaceCount)} detail={isAdmin ? "Workspace hierarchy" : user.group_paths[0] ?? "No space assigned"} loading={isAdmin && groupsQuery.isLoading} />
          <Metric icon={<Users size={20} />} label="Users" value={isAdmin ? valueOrUnavailable(userCount) : role} detail={isAdmin ? "Provisioned accounts" : `Permission v${user.permission_version}`} loading={isAdmin && usersQuery.isLoading} />
          <Metric icon={<FileCheck2 size={20} />} label="Review Queue" value={canReview ? valueOrUnavailable(pendingReviews) : "Restricted"} detail={canReview ? "Documents awaiting review" : "Reviewer access required"} loading={canReview && reviewQuery.isLoading} />
        </section>
          {documentsQuery.isError ? <InlineMessage tone="error">{errorMessage(documentsQuery.error, "Unable to load document counts.")}</InlineMessage> : null}
          {groupsQuery.isError ? <InlineMessage tone="error">{errorMessage(groupsQuery.error, "Unable to load Knowledge Space count.")}</InlineMessage> : null}
          {usersQuery.isError ? <InlineMessage tone="error">{errorMessage(usersQuery.error, "Unable to load user count.")}</InlineMessage> : null}
          {reviewQuery.isError ? <InlineMessage tone="warning">{errorMessage(reviewQuery.error, "Unable to load review queue.")}</InlineMessage> : null}

        {isPlatformAdmin(user) ? <SystemResources /> : null}
        {canAccessRoute(user, "activity-log") ? <WorkspaceActivity /> : null}
        <CorpusReadiness data={documentsQuery.data} loading={documentsQuery.isLoading} />
        <nav className="overview-shortcuts" aria-label="Operational workspaces">
          {visibleActions.map((action) => <a key={action.route} href={routePaths[action.route]} onClick={(event) => handleRouteClick(event, action.route, onNavigate)}>{action.icon}<span>{action.label}</span><ArrowRight size={14} aria-hidden="true" /></a>)}
        </nav>
      </div>
    </PrudentiaBasicPage>
  );
}

function handleRouteClick(event: MouseEvent<HTMLAnchorElement>, route: RouteId, onNavigate: (route: RouteId) => void) {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  onNavigate(route);
}

function Metric({ detail, icon, label, loading, value }: MetricProps) {
  return (
    <div className="sv-panel overview-summary-card" aria-busy={loading}>
      <span className="overview-summary-icon" aria-hidden="true">{icon}</span>
      <p className="overview-summary-label">{label}</p>
      {loading ? (
        <>
          <span className="sr-only">Loading {label.toLowerCase()}</span>
          <Skeleton className="mt-2 h-7 w-16" />
          <Skeleton className="mt-2 h-3 w-28" />
        </>
      ) : (
        <>
          <p className="overview-summary-value">{value}</p>
          <p className="overview-caption">{detail}</p>
        </>
      )}
    </div>
  );
}

function valueOrUnavailable(value: string | number | null): string {
  if (value === null || value === undefined || value === "") return "Unavailable";
  return typeof value === "number" ? value.toLocaleString() : value;
}

type SharedProps = {
  onLogout: () => void;
  onNavigate: (route: RouteId) => void;
  user: AuthUser;
};

type OverviewActionProps = {
  description: string;
  icon: JSX.Element;
  label: string;
  route: RouteId;
};

type MetricProps = {
  icon: JSX.Element;
  detail: string;
  label: string;
  loading: boolean;
  value: string;
};
