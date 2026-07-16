import { useEffect, useState } from "react";
import type { IngestJobOrigin, UploadJobState } from "@/types/api";

export function initialActivityStringParam(name: string) {
  if (typeof window === "undefined") return "";
  return new URLSearchParams(window.location.search).get(name)?.trim() ?? "";
}

export function useDebouncedText(value: string, delayMs: number) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delayMs);
    return () => window.clearTimeout(timer);
  }, [delayMs, value]);
  return debounced;
}

export function initialActivityOffsetFromUrl() {
  const value = Number.parseInt(initialActivityStringParam("offset"), 10);
  return Number.isFinite(value) && value > 0 ? value : 0;
}

export function initialJobOriginFromUrl(): IngestJobOrigin | "" {
  const value = initialActivityStringParam("origin");
  return isJobOrigin(value) ? value : "";
}

export function initialJobStatusFromUrl(): UploadJobState | "" {
  const value = initialActivityStringParam("status");
  return isJobStatus(value) ? value : "";
}

export function syncActivityUrl({ createdFrom, createdTo, groupPath, offset, origin, search, status }: ActivityUrlState) {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  url.searchParams.delete("search");
  setUrlParam(url.searchParams, "job_q", search.trim());
  setUrlParam(url.searchParams, "status", status);
  setUrlParam(url.searchParams, "origin", origin);
  setUrlParam(url.searchParams, "space", groupPath);
  setUrlParam(url.searchParams, "created_from", createdFrom);
  setUrlParam(url.searchParams, "created_to", createdTo);
  setUrlParam(url.searchParams, "offset", offset > 0 ? String(offset) : "");
  const next = `${url.pathname}${url.search}${url.hash}`;
  const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (next !== current) window.history.replaceState(window.history.state, "", next);
}

function setUrlParam(params: URLSearchParams, key: string, value: string) {
  if (value) params.set(key, value);
  else params.delete(key);
}

function isJobOrigin(value: string): value is IngestJobOrigin {
  return value === "upload" || value === "folder" || value === "connector" || value === "reingest" || value === "restore" || value === "unknown";
}

function isJobStatus(value: string): value is UploadJobState {
  return value === "scheduled" || value === "queued" || value === "processing" || value === "human_review" || value === "cancelled" || value === "failed" || value === "complete";
}

export type ActivityUrlState = { createdFrom: string; createdTo: string; groupPath: string; offset: number; origin: IngestJobOrigin | ""; search: string; status: UploadJobState | "" };
