import { useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent, PointerEvent, ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Database,
  FileSearch,
  FolderKanban,
  GripVertical,
  LayoutDashboard,
  LogOut,
  Menu,
  Moon,
  Search,
  Settings,
  ShieldCheck,
  Sun,
  Users,
  X,
  type LucideIcon,
} from "lucide-react";

import { documentsApi, ingestJobsApi, reviewApi } from "../../api/contracts";
import { FahamBrandMark } from "../brand/FahamBrand";
import {
  canAccessRoute,
  navigationGroupForRoute,
  visibleNavigation,
  type NavigationBadge,
  type NavigationIcon,
  type RouteId,
  type WorkspaceNavigationItem,
} from "../../routes";
import type { User as AuthUser } from "../../types/api";

export const FAHAM_SIDEBAR_MIN_WIDTH = 184;
export const FAHAM_SIDEBAR_MAX_WIDTH = 280;
export const FAHAM_SIDEBAR_DEFAULT_WIDTH = 208;
export const FAHAM_SIDEBAR_COLLAPSED_WIDTH = 56;

const iconByKey: Record<NavigationIcon, LucideIcon> = {
  audit: FolderKanban,
  documents: FileSearch,
  evaluations: Activity,
  overview: LayoutDashboard,
  query: Search,
  review: ShieldCheck,
  settings: Settings,
  spaces: Database,
  users: Users,
};

export function FahamSidebar({
  activeRoute,
  headerContent,
  isLightMode,
  onLogout,
  onNavigate,
  onSidebarCollapsedChange,
  onSidebarWidthChange,
  onToggleTheme,
  sidebarCollapsed,
  sidebarWidth,
  user,
}: Props) {
  const primarySpace = formatKnowledgeSpace(user.group_paths);
  const items = useMemo(() => visibleNavigation(user), [user]);
  const [expandedGroup, setExpandedGroup] = useState<string | null>(() => navigationGroupForRoute(activeRoute));
  const [mobileOpen, setMobileOpen] = useState(false);
  const drawerRef = useRef<HTMLElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
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

  useEffect(() => {
    setExpandedGroup(navigationGroupForRoute(activeRoute));
    setMobileOpen(false);
  }, [activeRoute]);

  useEffect(() => {
    document.body.classList.toggle("faham-mobile-nav-open", mobileOpen);
    if (mobileOpen) {
      requestAnimationFrame(() => drawerRef.current?.querySelector<HTMLElement>("[data-sidebar-first='true']")?.focus());
    }
    return () => document.body.classList.remove("faham-mobile-nav-open");
  }, [mobileOpen]);

  function badgeValue(badge: NavigationBadge | undefined): number | null {
    if (badge === "trash") return trashQuery.data?.total ?? null;
    if (badge === "jobs") {
      const summary = jobsSummaryQuery.data;
      return summary ? summary.active + (summary.status_counts.failed ?? 0) : null;
    }
    if (badge === "review") return reviewQuery.data?.total ?? null;
    return null;
  }

  function navigate(route: RouteId) {
    onNavigate(route);
    setMobileOpen(false);
  }

  function closeMobileDrawer() {
    setMobileOpen(false);
    triggerRef.current?.focus();
  }

  function handleDrawerKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      closeMobileDrawer();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = Array.from(
      drawerRef.current?.querySelectorAll<HTMLElement>(
        "button:not([disabled]), a[href], select:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex='-1'])",
      ) ?? [],
    ).filter((element) => element.offsetParent !== null);
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function handleResizeStart(event: PointerEvent<HTMLDivElement>) {
    if (sidebarCollapsed) return;
    if (event.button !== 0) return;
    event.preventDefault();

    const startX = event.clientX;
    const startWidth = sidebarWidth;
    const resizeHandle = event.currentTarget;
    resizeHandle.setPointerCapture(event.pointerId);
    document.body.classList.add("is-resizing-sidebar");

    const handlePointerMove = (moveEvent: globalThis.PointerEvent) => {
      onSidebarWidthChange(clampSidebarWidth(startWidth + moveEvent.clientX - startX));
    };

    const handlePointerUp = () => {
      document.body.classList.remove("is-resizing-sidebar");
      resizeHandle.removeEventListener("pointermove", handlePointerMove);
      resizeHandle.removeEventListener("pointerup", handlePointerUp);
      resizeHandle.removeEventListener("pointercancel", handlePointerUp);
    };

    resizeHandle.addEventListener("pointermove", handlePointerMove);
    resizeHandle.addEventListener("pointerup", handlePointerUp);
    resizeHandle.addEventListener("pointercancel", handlePointerUp);
  }

  function handleResizeKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (sidebarCollapsed) return;
    if (event.key === "ArrowLeft") onSidebarWidthChange(clampSidebarWidth(sidebarWidth - 8));
    else if (event.key === "ArrowRight") onSidebarWidthChange(clampSidebarWidth(sidebarWidth + 8));
    else if (event.key === "Home") onSidebarWidthChange(FAHAM_SIDEBAR_MIN_WIDTH);
    else if (event.key === "End") onSidebarWidthChange(FAHAM_SIDEBAR_MAX_WIDTH);
    else return;
    event.preventDefault();
  }

  const sidebarClassName = [
    "faham-sidebar",
    sidebarCollapsed ? "faham-sidebar-collapsed" : "",
    mobileOpen ? "faham-sidebar-mobile-open" : "",
  ].filter(Boolean).join(" ");

  return (
    <>
      <div className="faham-mobile-nav-bar">
        <div className="faham-mobile-brand">
          <FahamBrandMark className="faham-mobile-brand-mark" />
          <span>
            <strong>Faham AI</strong>
            <small>{items.find((item) => item.id === navigationGroupForRoute(activeRoute))?.label ?? "Workspace"}</small>
          </span>
        </div>
        <button ref={triggerRef} type="button" onClick={() => setMobileOpen(true)} aria-expanded={mobileOpen} aria-controls="faham-primary-sidebar" aria-label="Open workspace navigation">
          <Menu size={18} />
        </button>
      </div>
      <button type="button" className={mobileOpen ? "faham-sidebar-backdrop faham-sidebar-backdrop-visible" : "faham-sidebar-backdrop"} onClick={closeMobileDrawer} aria-label="Close workspace navigation" tabIndex={mobileOpen ? 0 : -1} />
      <aside
        ref={drawerRef}
        id="faham-primary-sidebar"
        className={sidebarClassName}
        aria-label="Workspace navigation"
        onKeyDown={handleDrawerKeyDown}
      >
        <div className="faham-sidebar-mobile-heading">
          <span className="faham-sidebar-mobile-heading-brand">
            <FahamBrandMark className="faham-mobile-brand-mark" />
            <strong>Faham AI</strong>
          </span>
          <button type="button" onClick={closeMobileDrawer} aria-label="Close workspace navigation">
            <X size={16} />
          </button>
        </div>
        <div className={headerContent ? "faham-sidebar-header faham-sidebar-header-context" : "faham-sidebar-header"}>
          {headerContent ? (
            <div className="faham-sidebar-product faham-sidebar-product-context">
              <div className="faham-sidebar-context-heading">
                <FahamBrandMark />
                <div className="min-w-0">
                  <h2>Faham AI</h2>
                </div>
                <SidebarCollapseButton
                  collapsed={sidebarCollapsed}
                  onToggle={() => onSidebarCollapsedChange(!sidebarCollapsed)}
                />
              </div>
              <div className="faham-sidebar-space-control">{headerContent}</div>
            </div>
          ) : (
            <div className="faham-sidebar-product">
              <FahamBrandMark />
              <div className="min-w-0">
                <h2 className="truncate text-label-md font-bold uppercase text-on-surface">Faham AI</h2>
                <p className="truncate text-[11px] font-semibold text-on-surface-variant">{primarySpace}</p>
              </div>
              <SidebarCollapseButton
                collapsed={sidebarCollapsed}
                onToggle={() => onSidebarCollapsedChange(!sidebarCollapsed)}
              />
            </div>
          )}
        </div>
        <nav className="faham-sidebar-nav" aria-label="Primary navigation">
          <SidebarItems
            activeRoute={activeRoute}
            badgeValue={badgeValue}
            expandedGroup={expandedGroup}
            items={items}
            sidebarCollapsed={sidebarCollapsed}
            onExpand={setExpandedGroup}
            onNavigate={navigate}
          />
        </nav>
        <div className="faham-sidebar-footer">
          <button
            type="button"
            onClick={() => navigate("account")}
            className={activeRoute === "account" ? "faham-account-button faham-account-button-active" : "faham-account-button"}
            aria-current={activeRoute === "account" ? "page" : undefined}
            aria-label={`Account management for ${user.email}`}
            title={`Account: ${user.email}`}
          >
            <div className="flex h-7 w-7 items-center justify-center rounded-full bg-primary-fixed text-on-primary-fixed text-[11px] font-bold">
              {user.email.slice(0, 2).toUpperCase()}
            </div>
            <div>
              <strong className="block max-w-48 truncate text-label-md text-on-surface">{user.email}</strong>
              <small className="text-secondary">{user.group_paths[0] ?? "No space"}</small>
            </div>
          </button>
          {onToggleTheme ? (
            <button
              type="button"
              role="switch"
              aria-checked={isLightMode}
              aria-label={isLightMode ? "Switch to dark mode" : "Switch to light mode"}
              className="faham-theme-switch"
              onClick={onToggleTheme}
              title="Theme"
            >
              <span className="faham-theme-switch-label">
                {isLightMode ? <Sun size={15} aria-hidden="true" /> : <Moon size={15} aria-hidden="true" />}
                <span>
                  <strong>Theme</strong>
                  <small>{isLightMode ? "Light mode" : "Dark mode"}</small>
                </span>
              </span>
              <span className="faham-switch-track" aria-hidden="true">
                <span />
              </span>
            </button>
          ) : null}
          {onLogout ? (
            <button type="button" onClick={onLogout} className="faham-signout-button" title="Sign out">
              <LogOut size={14} aria-hidden="true" />
              Sign out
            </button>
          ) : null}
        </div>
        {!sidebarCollapsed ? <div
          className="faham-sidebar-resize-handle"
          role="separator"
          aria-label="Resize sidebar"
          aria-orientation="vertical"
          aria-valuemax={FAHAM_SIDEBAR_MAX_WIDTH}
          aria-valuemin={FAHAM_SIDEBAR_MIN_WIDTH}
          aria-valuenow={sidebarWidth}
          onKeyDown={handleResizeKeyDown}
          onPointerDown={handleResizeStart}
          tabIndex={0}
        >
          <GripVertical size={12} aria-hidden="true" />
        </div> : null}
      </aside>
    </>
  );
}

function SidebarCollapseButton({ collapsed, onToggle }: SidebarCollapseButtonProps) {
  return (
    <button
      type="button"
      className="faham-sidebar-collapse-button"
      onClick={onToggle}
      aria-label={collapsed ? "Expand workspace navigation" : "Collapse workspace navigation"}
      aria-expanded={!collapsed}
      title={collapsed ? "Expand navigation" : "Collapse navigation"}
    >
      {collapsed ? <ChevronRight size={14} aria-hidden="true" /> : <ChevronLeft size={14} aria-hidden="true" />}
    </button>
  );
}

function SidebarItems({ activeRoute, badgeValue, expandedGroup, items, onExpand, onNavigate, sidebarCollapsed }: SidebarItemsProps) {
  let lastSection = "";
  let firstButton = true;
  return (
    <>
      {items.map((item) => {
        const showSection = item.section !== lastSection;
        lastSection = item.section;
        const Icon = iconByKey[item.icon];
        const active = item.route === activeRoute || item.children?.some((child) => child.route === activeRoute) === true;
        const expanded = item.children ? expandedGroup === item.id : false;
        const firstVisibleRoute = item.children?.[0]?.route ?? item.route;
        const dataFirst = firstButton ? { "data-sidebar-first": "true" } : {};
        firstButton = false;
        return (
          <div key={item.id} className="faham-nav-group">
            {showSection ? <p className="faham-sidebar-section">{item.section}</p> : null}
            <button
              {...dataFirst}
              type="button"
              onClick={() => {
                if (item.children) onExpand(item.id);
                if (firstVisibleRoute) onNavigate(firstVisibleRoute);
              }}
              className={active ? "faham-sidenav-item-active" : "faham-sidenav-item"}
              aria-current={!item.children && active ? "page" : undefined}
              aria-expanded={item.children && !sidebarCollapsed ? expanded : undefined}
              aria-label={item.label}
              title={item.label}
            >
              <Icon size={16} aria-hidden="true" />
              <span className="faham-nav-label">{item.label}</span>
              <NavigationBadgeCount count={badgeValue(item.badge)} />
              {item.children ? expanded ? <ChevronDown className="faham-nav-chevron" size={13} /> : <ChevronRight className="faham-nav-chevron" size={13} /> : null}
            </button>
            {item.children && expanded && !sidebarCollapsed ? (
              <div className="faham-sidenav-children">
                {item.children.map((child) => {
                  const count = badgeValue(child.badge);
                  const childActive = child.route === activeRoute;
                  return (
                    <button
                      key={child.route}
                      type="button"
                      onClick={() => onNavigate(child.route)}
                      className={childActive ? "faham-sidenav-child-active" : "faham-sidenav-child"}
                      aria-current={childActive ? "page" : undefined}
                    >
                      <span>{child.label}</span>
                      <NavigationBadgeCount count={count} />
                    </button>
                  );
                })}
              </div>
            ) : null}
          </div>
        );
      })}
    </>
  );
}

function NavigationBadgeCount({ count }: { count: number | null }) {
  if (count === null || count <= 0) return null;
  return <small aria-label={`${count} items`}>{count > 99 ? "99+" : count}</small>;
}

function formatKnowledgeSpace(paths: string[]): string {
  if (paths.length === 0) return "No space assigned";
  const [primary, ...rest] = paths;
  return rest.length ? `${primary} +${rest.length} more` : primary;
}

type Props = {
  activeRoute: RouteId;
  headerContent?: ReactNode;
  isLightMode: boolean;
  onLogout?: () => void;
  onNavigate: (route: RouteId) => void;
  onSidebarCollapsedChange: (collapsed: boolean) => void;
  onSidebarWidthChange: (width: number) => void;
  onToggleTheme?: () => void;
  sidebarCollapsed: boolean;
  sidebarWidth: number;
  user: AuthUser;
};

type SidebarItemsProps = {
  activeRoute: RouteId;
  badgeValue: (badge: NavigationBadge | undefined) => number | null;
  expandedGroup: string | null;
  items: WorkspaceNavigationItem[];
  onExpand: (group: string) => void;
  onNavigate: (route: RouteId) => void;
  sidebarCollapsed: boolean;
};

type SidebarCollapseButtonProps = {
  collapsed: boolean;
  onToggle: () => void;
};

function clampSidebarWidth(width: number): number {
  return Math.min(FAHAM_SIDEBAR_MAX_WIDTH, Math.max(FAHAM_SIDEBAR_MIN_WIDTH, width));
}
