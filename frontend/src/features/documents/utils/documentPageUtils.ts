import {
  canWriteDocument,
  clearanceLevelLabel,
  hasExactGroupScope,
  isGlobalAdmin,
  isGroupPathInUserScope,
} from "@/lib/auth/authz";
import { isUploadTerminalStatus } from "@/features/upload/state/uploadJobProgress";
import type { Document, DocumentIngestStatus, User as AuthUser } from "@/types/api";
import type { UploadBatchItemView } from "@/types/chat";
import { errorMessage } from "@/lib/utils/format";
import { isDocumentInSpace, type GroupOption } from "@/lib/utils/groups";

export type DocumentsView = "spaces" | "documents" | "trash";
export type ExplorerTab = { kind: "overview" } | { kind: "space"; path: string };
export type DocumentAction = "reingest" | "trash" | "restore" | "permanent";
export type DocumentMode = "active" | "trash" | "readonly";
export type DocumentStateFilter = "all" | "current" | "superseded";
export type DocumentIngestFilter = "all" | "indexed" | "active" | "processing" | "human_review" | "cancelled" | "failed" | "unknown";
export type SpaceDraft = { name: string; path: string; pathTouched: boolean };

export type ExplorerUrlState = {
  activeTab: ExplorerTab;
  documentSearch: string;
  ingestFilter: DocumentIngestFilter;
  selectedDocumentId: string | null;
  spaceFilter: string;
  statusFilter: DocumentStateFilter;
  view: DocumentsView;
};

export type SpaceOverviewRow = {
  currentCount: number;
  documentsCount: number;
  failedCount: number;
  processingCount: number;
  reviewCount: number;
  unknownCount: number;
  space: GroupOption;
};

export function documentsForView(
  view: DocumentsView,
  activeTab: ExplorerTab,
  activeDocuments: Document[],
  deletedDocuments: Document[],
  search: string,
  statusFilter: DocumentStateFilter,
  ingestFilter: DocumentIngestFilter,
  spaceFilter: string,
) {
  const source = view === "trash"
    ? deletedDocuments
    : view === "documents"
      ? activeDocuments
      : activeTab.kind === "space"
        ? activeDocuments.filter((doc) => documentAccessPaths(doc).includes(activeTab.path))
        : [];
  return source.filter((doc) => matchesSpace(doc, view, spaceFilter) && matchesDoc(doc, search) && matchesStatus(doc, statusFilter) && matchesIngestStatus(doc.ingest_status, ingestFilter));
}

export function uniqueTopicValues(values: string[]): string[] {
  const seen = new Set<string>();
  const topics: string[] = [];
  values.forEach((value) => {
    const topic = value.trim();
    const key = topic.toLowerCase();
    if (topic && !seen.has(key)) {
      seen.add(key);
      topics.push(topic);
    }
  });
  return topics;
}

export function isProcessingIngestStatus(status: DocumentIngestStatus) {
  return status === "queued" || status === "scheduled" || status === "processing";
}

export function buildSpaceOverviewRows(spaces: GroupOption[], documents: Document[], uploadJobs: UploadBatchItemView[]): SpaceOverviewRow[] {
  return spaces.map((space) => {
    const scopedDocuments = documents.filter((doc) => isDocumentVisibleInSpace(doc, space.path));
    const scopedJobs = uploadJobs.filter((job) => isDocumentInSpace(job.groupPath, space.path));
    return {
      currentCount: scopedDocuments.filter((doc) => doc.is_current).length,
      documentsCount: scopedDocuments.length,
      failedCount: scopedDocuments.filter((doc) => doc.ingest_status === "failed").length + scopedJobs.filter(isFailedUploadJob).length,
      processingCount: scopedDocuments.filter((doc) => isProcessingIngestStatus(doc.ingest_status)).length + scopedJobs.filter(isActiveUploadJob).length,
      reviewCount: scopedDocuments.filter((doc) => doc.ingest_status === "human_review").length + scopedJobs.filter((job) => job.job?.status === "human_review").length,
      unknownCount: scopedDocuments.filter((doc) => doc.ingest_status === "unknown").length,
      space,
    };
  });
}

export function mergeSpaceOptions(spaceOptions: GroupOption[], documents: Document[], selectedPath = "") {
  const seen = new Set<string>();
  const merged: GroupOption[] = [];
  spaceOptions.forEach((space) => {
    if (seen.has(space.path)) return;
    seen.add(space.path);
    merged.push(space);
  });
  documents
    .flatMap((doc) => documentAccessPaths(doc))
    .filter((path) => path && !seen.has(path))
    .sort((a, b) => a.localeCompare(b))
    .forEach((path) => {
      seen.add(path);
      merged.push(spaceFromPath(path));
    });
  const selected = selectedPath.trim();
  if (selected && !seen.has(selected)) merged.push(spaceFromPath(selected));
  return merged;
}

export function scopeLine(document: Document) {
  if (!document.shared_group_paths.length) return "Owner only";
  return `Shared to ${document.shared_group_paths.length}`;
}

export function sortedSpaceOverviewRows(rows: SpaceOverviewRow[]) {
  return [...rows].sort((a, b) => {
    const attentionDelta = spaceAttentionCount(b) - spaceAttentionCount(a);
    if (attentionDelta !== 0) return attentionDelta;
    const documentDelta = b.documentsCount - a.documentsCount;
    if (documentDelta !== 0) return documentDelta;
    return a.space.path.localeCompare(b.space.path);
  });
}

export function spaceAttentionCount(row: SpaceOverviewRow) {
  return row.processingCount + row.reviewCount + row.failedCount + row.unknownCount;
}

export function spaceHealth(row: SpaceOverviewRow): { label: string; tone: "active" | "danger" | "success" | "warning" } {
  if (row.failedCount > 0) return { label: `${row.failedCount} failed`, tone: "danger" };
  if (row.reviewCount > 0) return { label: `${row.reviewCount} review`, tone: "warning" };
  if (row.processingCount > 0) return { label: `${row.processingCount} active`, tone: "active" };
  if (row.unknownCount > 0) return { label: `${row.unknownCount} unknown`, tone: "warning" };
  return { label: "Healthy", tone: "success" };
}

export function canModifyDocument(user: AuthUser, document: Document) {
  if (document.governance_owner === "system" && !isGlobalAdmin(user)) return false;
  return canWriteDocument(user, document.owner_group_path ?? document.group_path, document.clearance_level);
}

export function canTransferDocumentOwner(user: AuthUser, document: Document) {
  const ownerGroupPath = document.owner_group_path ?? document.group_path;
  return isGlobalAdmin(user) || (user.account_type === "space_admin" && hasExactGroupScope(user, ownerGroupPath));
}

export function ownershipTransferOptions(user: AuthUser, ownerGroupPath: string, spaceOptions: GroupOption[]) {
  const currentOwner = ownerGroupPath.trim();
  if (!currentOwner) return [];
  const candidates = spaceOptions.filter((space) => space.path !== currentOwner);
  if (isGlobalAdmin(user)) return candidates;
  if (user.account_type !== "space_admin" || !hasExactGroupScope(user, currentOwner)) return [];
  return candidates.filter((space) => hasExactGroupScope(user, space.path));
}

export function canPermanentlyDeleteDocument(user: AuthUser, document: Document) {
  if (document.governance_owner === "system") return isGlobalAdmin(user);
  const groupPath = document.owner_group_path ?? document.group_path;
  return isGlobalAdmin(user) || (user.account_type === "space_admin" && isGroupPathInUserScope(user, groupPath));
}

export function canUnshareTargetSpace(user: AuthUser, groupPath: string) {
  return isGlobalAdmin(user) || (user.account_type === "space_admin" && isGroupPathInUserScope(user, groupPath));
}

export function confirmDocumentAction(action: DocumentAction, documents: Document[]) {
  if (action === "trash") {
    return window.confirm(`Move ${documents.length} document${documents.length === 1 ? "" : "s"} to Trash? Indexed vectors will be removed immediately.`);
  }
  if (action === "permanent") {
    const expected = documents.length === 1 ? "DELETE" : `DELETE ${documents.length}`;
    const entered = window.prompt(`Permanent deletion removes database records and source files. Type ${expected} to continue.`);
    return entered === expected;
  }
  return true;
}

export async function runBounded<T>(
  items: T[],
  concurrency: number,
  worker: (item: T) => Promise<unknown>,
): Promise<Array<{ item: T; ok: true } | { item: T; ok: false; message: string }>> {
  const results: Array<{ item: T; ok: true } | { item: T; ok: false; message: string }> = [];
  let index = 0;
  async function next() {
    while (index < items.length) {
      const item = items[index];
      index += 1;
      try {
        await worker(item);
        results.push({ item, ok: true });
      } catch (error) {
        results.push({ item, ok: false, message: errorMessage(error, "Request failed.") });
      }
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, items.length) }, next));
  return results;
}

export function ingestStatusLabel(status: DocumentIngestStatus) {
  if (status === "human_review") return "Needs review";
  if (status === "processing") return "Processing";
  if (status === "scheduled") return "Scheduled";
  if (status === "queued") return "Queued";
  if (status === "cancelled") return "Cancelled";
  if (status === "failed") return "Failed";
  if (status === "unknown") return "Unknown";
  return "Indexed";
}

export function labelize(value: string | null | undefined) {
  if (!value) return "Unknown";
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function spaceFromPath(path: string): GroupOption {
  const name = path.split("/").filter(Boolean).at(-1)?.replace(/-/g, " ") || path;
  return {
    depth: Math.max(0, path.split("/").filter(Boolean).length - 1),
    name: name.replace(/\b\w/g, (letter) => letter.toUpperCase()),
    parentPath: null,
    path,
  };
}

export function initialExplorerTabFromUrl(): ExplorerTab {
  const space = initialStringParamFromUrl("space");
  if (space) return { kind: "space", path: space };
  return { kind: "overview" };
}

export function initialDocumentStateFilterFromUrl(): DocumentStateFilter {
  const value = initialStringParamFromUrl("lifecycle");
  return isDocumentStateFilter(value) ? value : "all";
}

export function initialDocumentIngestFilterFromUrl(): DocumentIngestFilter {
  const value = initialStringParamFromUrl("ingest");
  return isDocumentIngestFilter(value) ? value : "all";
}

export function initialStringParamFromUrl(name: string) {
  if (typeof window === "undefined") return "";
  return new URLSearchParams(window.location.search).get(name)?.trim() ?? "";
}

export function syncExplorerUrl({ activeTab, documentSearch, ingestFilter, selectedDocumentId, spaceFilter, statusFilter, view }: ExplorerUrlState) {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  url.searchParams.delete("tab");
  setUrlParam(url.searchParams, "space", view === "spaces" && activeTab.kind === "space" ? activeTab.path : view === "documents" || view === "trash" ? spaceFilter.trim() : "");
  setUrlParam(url.searchParams, "doc", selectedDocumentId ?? "");
  setUrlParam(url.searchParams, "doc_q", documentSearch.trim());
  setUrlParam(url.searchParams, "lifecycle", statusFilter === "all" ? "" : statusFilter);
  setUrlParam(url.searchParams, "ingest", ingestFilter === "all" ? "" : ingestFilter);
  const next = `${url.pathname}${url.search}${url.hash}`;
  const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (next !== current) window.history.replaceState(window.history.state, "", next);
}

export function explorerTabKey(tab: ExplorerTab) {
  return tab.kind === "space" ? `space:${tab.path}` : tab.kind;
}

export function createSpaceDraft(): SpaceDraft {
  return {
    name: "",
    path: "",
    pathTouched: false,
  };
}

function matchesSpace(doc: Document, view: DocumentsView, spaceFilter: string) {
  const selectedSpace = spaceFilter.trim();
  if (!selectedSpace || view === "spaces") return true;
  return isDocumentVisibleInSpace(doc, selectedSpace);
}

function matchesDoc(doc: Document, search: string) {
  const q = search.toLowerCase().trim();
  if (!q) return true;
  return [
    doc.title,
    doc.id,
    doc.owner_group_path ?? doc.group_path,
    ...doc.shared_group_paths,
    clearanceLevelLabel(doc.clearance_level),
    doc.summary ?? "",
    doc.description ?? "",
    ...doc.topics,
    ...doc.llm_topics,
    ...doc.entities.map((entity) => entity.text),
  ].join(" ").toLowerCase().includes(q);
}

function matchesStatus(doc: Document, status: DocumentStateFilter) {
  return status === "all" || (status === "current" ? doc.is_current : !doc.is_current);
}

function matchesIngestStatus(status: DocumentIngestStatus, filter: DocumentIngestFilter) {
  if (filter === "all") return true;
  if (filter === "indexed") return status === "complete";
  if (filter === "active") return status !== "complete";
  if (filter === "processing") return isProcessingIngestStatus(status);
  return status === filter;
}

function isActiveUploadJob(item: UploadBatchItemView) {
  if (item.requestState === "uploading") return true;
  if (item.requestState === "failed") return false;
  return !isUploadTerminalStatus(item.job?.status);
}

function isFailedUploadJob(item: UploadBatchItemView) {
  return item.requestState === "failed" || item.job?.status === "failed";
}

function documentAccessPaths(document: Document) {
  const paths = document.access_group_paths?.length
    ? document.access_group_paths
    : [document.owner_group_path ?? document.group_path, ...document.shared_group_paths];
  return Array.from(new Set(paths.filter(Boolean)));
}

function isDocumentVisibleInSpace(document: Document, spacePath: string) {
  return documentAccessPaths(document).some((path) => isDocumentInSpace(path, spacePath));
}

function setUrlParam(params: URLSearchParams, key: string, value: string) {
  if (value) params.set(key, value);
  else params.delete(key);
}

function isDocumentStateFilter(value: string): value is DocumentStateFilter {
  return value === "all" || value === "current" || value === "superseded";
}

function isDocumentIngestFilter(value: string): value is DocumentIngestFilter {
  return value === "all" || value === "indexed" || value === "active" || value === "processing" || value === "human_review" || value === "cancelled" || value === "failed" || value === "unknown";
}
