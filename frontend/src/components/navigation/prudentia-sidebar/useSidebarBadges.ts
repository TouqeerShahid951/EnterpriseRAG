import { useQuery } from "@tanstack/react-query";

import { documentsApi, ingestJobsApi, reviewApi } from "@/lib/api/contracts";
import { canAccessRoute, type NavigationBadge } from "@/routes/routes";
import type { User as AuthUser } from "@/types/api";

export type SidebarBadgeValue = (badge: NavigationBadge | undefined) => number | null;

export function useSidebarBadges(user: AuthUser): SidebarBadgeValue {
  const jobsSummaryQuery = useQuery({
    queryKey: ["ingest-jobs", "summary"],
    queryFn: () => ingestJobsApi.summary(),
    enabled: canAccessRoute(user, "ingestion-jobs"),
    refetchInterval: 5000,
    staleTime: 4000,
    retry: false,
  });
  const trashQuery = useQuery({
    queryKey: ["documents", "list", "deleted"],
    queryFn: () => documentsApi.list({ state: "deleted" }),
    enabled: canAccessRoute(user, "document-trash"),
    staleTime: 15000,
    retry: false,
  });
  const reviewQuery = useQuery({
    queryKey: ["review-queue"],
    queryFn: reviewApi.list,
    enabled: canAccessRoute(user, "review"),
    refetchInterval: 5000,
    staleTime: 4000,
    retry: false,
  });
  const imageReviewQuery = useQuery({
    queryKey: ["review-queue", "image-batches"],
    queryFn: reviewApi.listImageBatches,
    enabled: canAccessRoute(user, "review"),
    refetchInterval: 5000,
    staleTime: 4000,
    retry: false,
  });

  return function badgeValue(badge: NavigationBadge | undefined): number | null {
    if (badge === "trash") return trashQuery.data?.total ?? null;
    if (badge === "jobs") {
      const summary = jobsSummaryQuery.data;
      return summary ? summary.needs_attention : null;
    }
    if (badge === "review") return reviewQueueBadgeCount(reviewQuery.data?.total, imageReviewQuery.data?.candidate_total);
    return null;
  };
}

export function reviewQueueBadgeCount(ocrTotal: number | null | undefined, imageCandidateTotal: number | null | undefined): number | null {
  if (ocrTotal == null && imageCandidateTotal == null) return null;
  return (ocrTotal ?? 0) + (imageCandidateTotal ?? 0);
}
