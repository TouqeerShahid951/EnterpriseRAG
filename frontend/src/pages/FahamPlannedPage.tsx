import { useQuery } from "@tanstack/react-query";
import { Activity, Clock3, FileText, Search, Upload, Users } from "lucide-react";

import { adminApi, reviewApi } from "../api/contracts";
import { accountTypeLabel, isGlobalAdmin } from "../authz";
import { InlineMessage, Skeleton } from "../components/layout/Common";
import { FahamBasicPage } from "../components/layout/FahamWorkspace";
import { canAccessRoute, type RouteId } from "../routes";
import type { Document, User as AuthUser } from "../types/api";
import { errorMessage } from "../utils/format";
import { countGroups } from "../utils/groups";

export function FahamOverviewPage({ documents, documentsLoading, onLogout, onNavigate, user }: OverviewProps) {
  const isAdmin = isGlobalAdmin(user);
  const canReview = canAccessRoute(user, "review");
  const role = accountTypeLabel(user.account_type);
  const canQuery = canAccessRoute(user, "chat");
  const canUpload = canAccessRoute(user, "upload");
  const currentCount = documents.filter((doc) => doc.is_current).length;
  const supersededCount = documents.length - currentCount;

  const groupsQuery = useQuery({ queryKey: ["admin", "groups"], queryFn: adminApi.listGroups, enabled: isAdmin, retry: false });
  const usersQuery = useQuery({ queryKey: ["admin", "users"], queryFn: adminApi.listUsers, enabled: isAdmin, retry: false });
  const reviewQuery = useQuery({ queryKey: ["review", "queue"], queryFn: reviewApi.list, enabled: canReview, retry: false });

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

  return (
    <FahamBasicPage activeRoute="overview" onLogout={onLogout} onNavigate={onNavigate} title="Workspace Summary" subtitle="High-level corpus, access, and review facts with shortcuts into focused operational workspaces." user={user}>
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
          <div className="mt-6 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <Metric label="Current documents" value={String(currentCount)} detail={`${supersededCount} superseded`} loading={documentsLoading} />
            <Metric label="Knowledge Spaces" value={valueOrUnavailable(spaceCount)} detail={isAdmin ? "Workspace hierarchy" : user.group_paths[0] ?? "No space assigned"} loading={isAdmin && groupsQuery.isLoading} />
            <Metric label="Users" value={isAdmin ? valueOrUnavailable(userCount) : role} detail={isAdmin ? "Provisioned accounts" : `Permission v${user.permission_version}`} loading={isAdmin && usersQuery.isLoading} />
            <Metric label="Review Queue" value={canReview ? valueOrUnavailable(pendingReviews) : "Restricted"} detail={canReview ? "Pending review items" : "Reviewer access required"} loading={canReview && reviewQuery.isLoading} />
          </div>
          {groupsQuery.isError ? <InlineMessage tone="error">{errorMessage(groupsQuery.error, "Unable to load Knowledge Space count.")}</InlineMessage> : null}
          {usersQuery.isError ? <InlineMessage tone="error">{errorMessage(usersQuery.error, "Unable to load user count.")}</InlineMessage> : null}
          {reviewQuery.isError ? <InlineMessage tone="warning">{errorMessage(reviewQuery.error, "Unable to load review queue.")}</InlineMessage> : null}
        </section>

        <section className="grid gap-4 lg:grid-cols-4">
          {visibleActions.map((action) => (
            <OverviewAction key={action.label} {...action} />
          ))}
        </section>
      </div>
    </FahamBasicPage>
  );
}

export function FahamPlannedPage({ activeRoute, onLogout, onNavigate, subtitle, title, user }: PlannedProps) {
  const canQuery = canAccessRoute(user, "chat");
  const canUpload = canAccessRoute(user, "upload");
  const canViewSpaces = canAccessRoute(user, "knowledge-spaces");

  return (
    <FahamBasicPage activeRoute={activeRoute} onLogout={onLogout} onNavigate={onNavigate} title={title} subtitle={subtitle} user={user}>
      <section className="sv-panel p-6">
        <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-lg border border-primary/20 bg-primary/10 text-primary">
          <Clock3 size={22} />
        </div>
        <p className="max-w-2xl text-body-lg font-semibold text-on-surface">This area is planned and not presented as a live feature yet.</p>
        <p className="mt-2 max-w-2xl text-body-md text-on-surface-variant">
          The active workflow is Document Intake for adding sources, Document Library for indexed files and access boundaries, and Query Intelligence for grounded answers.
        </p>
        {canQuery || canUpload || canViewSpaces ? (
          <div className="mt-5 flex flex-wrap gap-3">
            {canQuery ? (
              <button type="button" onClick={() => onNavigate("chat")} className="sv-action-primary">
                Open Query Intelligence
              </button>
            ) : null}
            {canUpload ? (
              <button type="button" onClick={() => onNavigate("upload")} className="sv-action-secondary">
                Open Document Intake
              </button>
            ) : null}
            {!canQuery && !canUpload && canViewSpaces ? (
              <button type="button" onClick={() => onNavigate("knowledge-spaces")} className="sv-action-secondary">
                Open Knowledge Spaces
              </button>
            ) : null}
          </div>
        ) : null}
      </section>
    </FahamBasicPage>
  );
}

function OverviewAction({ description, icon, label, onClick }: OverviewActionProps) {
  return (
    <button type="button" onClick={onClick} className="sv-card p-5 text-left transition-colors hover:bg-surface-container-high" data-cursor-glow>
      <span className="mb-4 flex h-10 w-10 items-center justify-center rounded-lg border border-primary/20 bg-primary/10 text-primary">{icon}</span>
      <strong className="block text-headline-sm text-on-surface">{label}</strong>
      <span className="mt-2 block text-body-md text-on-surface-variant">{description}</span>
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

type PlannedProps = SharedProps & {
  activeRoute: RouteId;
  subtitle: string;
  title: string;
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
