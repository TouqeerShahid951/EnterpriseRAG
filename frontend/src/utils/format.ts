import { ApiClientError } from "../api/client";
import type { RAGResponse } from "../types/api";

export function todayInputValue(): string {
  return new Date().toISOString().slice(0, 10);
}

export function formatDate(value: string | null | undefined): string {
  if (!value) {
    return "Not set";
  }
  return value.slice(0, 10);
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return "Never";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export function formatIntent(intent: RAGResponse["intent"]): string {
  return intent.replace(/_/g, " ");
}

export function formatScore(score: number): string {
  return `${Math.round(score * 100)}%`;
}

export function errorMessage(error: unknown, fallback = "Request failed."): string {
  if (error instanceof ApiClientError) {
    return error.error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return fallback;
}

export function splitPathList(value: string): string[] {
  return value
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);
}
