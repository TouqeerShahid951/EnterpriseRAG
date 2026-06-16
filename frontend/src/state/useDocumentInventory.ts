import { useQuery } from "@tanstack/react-query";
import { documentsApi } from "../api/contracts";
import type { User } from "../types/api";

export function useDocumentInventory(currentUser: User | null) {
  const documentsQuery = useQuery({
    queryKey: ["documents", "list"],
    queryFn: () => documentsApi.list(),
    retry: false,
    enabled: Boolean(currentUser),
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

function parseDate(value: string | null): number {
  return value ? Date.parse(value) : 0;
}
