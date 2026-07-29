import { useQuery } from "@tanstack/react-query";

import { documentsApi, reviewApi } from "@/lib/api/contracts";
import { canAccessRoute, type NavigationBadge } from "@/routes/routes";
import type { User as AuthUser } from "@/types/api";

export type SidebarBadgeValue = (badge: NavigationBadge | undefined) => number | null;

export function useSidebarBadges(user: AuthUser): SidebarBadgeValue {
  const documentOverviewQuery = useQuery({
    queryKey: ["documents", "overview"],
    queryFn: documentsApi.overview,
    enabled: canAccessRoute(user, "document-trash"),
    staleTime: 15000,
    retry: false,
  });
  const reviewSummaryQuery = useQuery({
    queryKey: ["review-queue", "summary"],
    queryFn: reviewApi.summary,
    enabled: canAccessRoute(user, "review"),
    refetchInterval: 10000,
    staleTime: 8000,
    retry: false,
  });

  return function badgeValue(badge: NavigationBadge | undefined): number | null {
    if (badge === "trash") return documentOverviewQuery.data?.trash ?? null;
    if (badge === "review") return reviewSummaryQuery.data?.pending_document_count ?? null;
    return null;
  };
}
