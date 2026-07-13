import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  GripVertical,
  LogOut,
  Menu,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  Sun,
  X,
} from "lucide-react";

import { PrudentiaBrandMark } from "@/components/brand/PrudentiaBrand";
import {
  navigationGroupForRoute,
  visibleNavigation,
  type RouteId,
} from "@/routes/routes";
import type { User as AuthUser } from "@/types/api";
import { SidebarMenu } from "./prudentia-sidebar/SidebarMenu";
import { useSidebarBadges } from "./prudentia-sidebar/useSidebarBadges";
import { useSidebarDrawer } from "./prudentia-sidebar/useSidebarDrawer";
import {
  Prudentia_SIDEBAR_MAX_WIDTH,
  Prudentia_SIDEBAR_MIN_WIDTH,
  useSidebarResize,
} from "./prudentia-sidebar/useSidebarResize";

export {
  Prudentia_SIDEBAR_COLLAPSED_WIDTH,
  Prudentia_SIDEBAR_MAX_WIDTH,
  Prudentia_SIDEBAR_MIN_WIDTH,
  getPrudentiaSidebarDefaultWidth,
} from "./prudentia-sidebar/useSidebarResize";
export { reviewQueueBadgeCount } from "./prudentia-sidebar/useSidebarBadges";

export function PrudentiaSidebar({
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
  const userGroupPaths = user.group_paths ?? [];
  const userEmail = user.email ?? "Unknown user";
  const primarySpace = formatKnowledgeSpace(userGroupPaths);
  const items = useMemo(() => visibleNavigation(user), [user]);
  const [expandedGroup, setExpandedGroup] = useState<string | null>(() => navigationGroupForRoute(activeRoute));
  const badgeValue = useSidebarBadges(user);

  useEffect(() => {
    setExpandedGroup(navigationGroupForRoute(activeRoute));
  }, [activeRoute]);

  const drawer = useSidebarDrawer(activeRoute);
  const resize = useSidebarResize({ onSidebarWidthChange, sidebarCollapsed, sidebarWidth });

  function navigate(route: RouteId) {
    onNavigate(route);
    drawer.dismiss();
  }

  const sidebarClassName = [
    "Prudentia-sidebar",
    sidebarCollapsed ? "Prudentia-sidebar-collapsed" : "",
    drawer.mobileOpen ? "Prudentia-sidebar-mobile-open" : "",
  ].filter(Boolean).join(" ");

  return (
    <>
      <div className="Prudentia-mobile-nav-bar">
        <div className="Prudentia-mobile-brand">
          <PrudentiaBrandMark className="Prudentia-mobile-brand-mark" />
          <span>
            <strong>Prudentia AI</strong>
            <small>{items.find((item) => item.id === navigationGroupForRoute(activeRoute))?.label ?? "Workspace"}</small>
          </span>
        </div>
        <button ref={drawer.triggerRef} type="button" onClick={drawer.open} aria-expanded={drawer.mobileOpen} aria-controls="Prudentia-primary-sidebar" aria-label="Open workspace navigation">
          <Menu size={18} />
        </button>
      </div>
      <button type="button" className={drawer.mobileOpen ? "Prudentia-sidebar-backdrop Prudentia-sidebar-backdrop-visible" : "Prudentia-sidebar-backdrop"} onClick={drawer.closeAndRestoreFocus} aria-label="Close workspace navigation" tabIndex={drawer.mobileOpen ? 0 : -1} />
      <aside
        ref={drawer.drawerRef}
        id="Prudentia-primary-sidebar"
        className={sidebarClassName}
        aria-label="Workspace navigation"
        onKeyDown={drawer.onKeyDown}
      >
        <div className="Prudentia-sidebar-mobile-heading">
          <span className="Prudentia-sidebar-mobile-heading-brand">
            <PrudentiaBrandMark className="Prudentia-mobile-brand-mark" />
            <strong>Prudentia AI</strong>
          </span>
          <button type="button" onClick={drawer.closeAndRestoreFocus} aria-label="Close workspace navigation">
            <X size={16} />
          </button>
        </div>
        <div className={headerContent ? "Prudentia-sidebar-header Prudentia-sidebar-header-context" : "Prudentia-sidebar-header"}>
          {headerContent ? (
            <div className="Prudentia-sidebar-product Prudentia-sidebar-product-context">
              <div className="Prudentia-sidebar-context-heading">
                <PrudentiaBrandMark />
                <div className="min-w-0">
                  <h2>Prudentia AI</h2>
                </div>
                <SidebarCollapseButton
                  collapsed={sidebarCollapsed}
                  onToggle={() => onSidebarCollapsedChange(!sidebarCollapsed)}
                />
              </div>
              <div className="Prudentia-sidebar-space-control">{headerContent}</div>
            </div>
          ) : (
            <div className="Prudentia-sidebar-product">
              <PrudentiaBrandMark />
              <div className="min-w-0">
                <h2 className="truncate text-label-md font-bold uppercase text-on-surface">Prudentia AI</h2>
                <p className="truncate text-[11px] font-semibold text-on-surface-variant">{primarySpace}</p>
              </div>
              <SidebarCollapseButton
                collapsed={sidebarCollapsed}
                onToggle={() => onSidebarCollapsedChange(!sidebarCollapsed)}
              />
            </div>
          )}
        </div>
        <nav className="Prudentia-sidebar-nav" aria-label="Primary navigation">
          <SidebarMenu
            activeRoute={activeRoute}
            badgeValue={badgeValue}
            expandedGroup={expandedGroup}
            items={items}
            sidebarCollapsed={sidebarCollapsed}
            onExpand={setExpandedGroup}
            onNavigate={navigate}
          />
        </nav>
        <div className="Prudentia-sidebar-footer">
          <button
            type="button"
            onClick={() => navigate("account")}
            className={activeRoute === "account" ? "Prudentia-account-button Prudentia-account-button-active" : "Prudentia-account-button"}
            aria-current={activeRoute === "account" ? "page" : undefined}
            aria-label={`Account management for ${userEmail}`}
            title={`Account: ${userEmail}`}
          >
            <div className="flex h-7 w-7 items-center justify-center rounded-full bg-primary-fixed text-on-primary-fixed text-[11px] font-bold">
              {userEmail.slice(0, 2).toUpperCase()}
            </div>
            <div>
              <strong className="block max-w-48 truncate text-label-md text-on-surface">{userEmail}</strong>
              <small className="text-secondary">{userGroupPaths[0] ?? "No space"}</small>
            </div>
          </button>
          {onToggleTheme ? (
            <button
              type="button"
              role="switch"
              aria-checked={isLightMode}
              aria-label={isLightMode ? "Switch to dark mode" : "Switch to light mode"}
              className="Prudentia-theme-switch"
              onClick={onToggleTheme}
              title="Theme"
            >
              <span className="Prudentia-theme-switch-label">
                {isLightMode ? <Sun size={15} aria-hidden="true" /> : <Moon size={15} aria-hidden="true" />}
                <span>
                  <strong>Theme</strong>
                  <small>{isLightMode ? "Light mode" : "Dark mode"}</small>
                </span>
              </span>
              <span className="Prudentia-switch-track" aria-hidden="true">
                <span />
              </span>
            </button>
          ) : null}
          {onLogout ? (
            <button type="button" onClick={onLogout} className="Prudentia-signout-button" title="Sign out">
              <LogOut size={14} aria-hidden="true" />
              Sign out
            </button>
          ) : null}
        </div>
        {!sidebarCollapsed ? <div
          className="Prudentia-sidebar-resize-handle"
          role="separator"
          aria-label="Resize sidebar"
          aria-orientation="vertical"
          aria-valuemax={Prudentia_SIDEBAR_MAX_WIDTH}
          aria-valuemin={Prudentia_SIDEBAR_MIN_WIDTH}
          aria-valuenow={sidebarWidth}
          onKeyDown={resize.onKeyDown}
          onPointerDown={resize.onPointerDown}
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
      className="Prudentia-sidebar-collapse-button"
      onClick={onToggle}
      aria-label={collapsed ? "Expand workspace navigation" : "Collapse workspace navigation"}
      aria-expanded={!collapsed}
      title={collapsed ? "Expand navigation" : "Collapse navigation"}
    >
      {collapsed ? (
        <span className="Prudentia-sidebar-collapse-logo" aria-hidden="true">
          <PrudentiaBrandMark />
        </span>
      ) : null}
      <span className="Prudentia-sidebar-collapse-icon" aria-hidden="true">
        {collapsed ? <PanelLeftOpen size={15} /> : <PanelLeftClose size={15} />}
      </span>
    </button>
  );
}

function formatKnowledgeSpace(paths: string[]): string {
  if (paths.length === 0) return "No space assigned";
  const [primary, ...rest] = paths;
  return rest.length ? `${primary} +${rest.length} more` : primary;
}

interface Props {
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
}

interface SidebarCollapseButtonProps {
  collapsed: boolean;
  onToggle: () => void;
}
