import { useQuery } from "@tanstack/react-query";
import { documentsApi } from "@/lib/api/contracts";
import type { User } from "@/types/api";

export function useDocumentInventory(currentUser: User | null, enabled = true) {
  const documentsQuery = useQuery({
    queryKey: ["documents", "list", "active"],
    queryFn: () => documentsApi.list(),
    retry: false,
    staleTime: 5000,
    enabled: Boolean(currentUser) && enabled,
  });

  const documents = documentsQuery.data?.items ?? [];
  const currentDocuments = documents
    .filter((item) => item.is_current)
    .sort((left, right) => parseDate(right.created_at) - parseDate(left.created_at));

  return {
    currentDocuments,
    documents,
    documentsQuery,
    latestCurrentDocument: currentDocuments[0] ?? null,
  };
}

export function useDocumentCatalogSummary(currentUser: User | null, enabled = true) {
  const summaryQuery = useQuery({
    queryKey: ["documents", "summary"],
    queryFn: () => documentsApi.summary(),
    retry: false,
    staleTime: 5000,
    enabled: Boolean(currentUser) && enabled,
  });

  return {
    groups: summaryQuery.data?.groups ?? [],
    summaryQuery,
    total: summaryQuery.data?.total ?? 0,
  };
}

function parseDate(value: string | null): number {
  return value ? Date.parse(value) : 0;
}
