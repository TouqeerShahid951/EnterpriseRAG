import {
  Activity,
  ChevronDown,
  ChevronRight,
  Database,
  FileSearch,
  FolderKanban,
  LayoutDashboard,
  Search,
  Settings,
  ShieldCheck,
  Users,
  type LucideIcon,
} from "lucide-react";
import type { MouseEvent } from "react";

import { routePaths, type NavigationBadge, type NavigationIcon, type RouteId, type WorkspaceNavigationItem } from "@/routes/routes";
import type { SidebarBadgeValue } from "./useSidebarBadges";

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

export function SidebarMenu({ activeRoute, badgeValue, expandedGroup, items, onExpand, onNavigate, sidebarCollapsed }: SidebarMenuProps) {
  let lastSection = "";
  let firstButton = true;

  function navigate(event: MouseEvent<HTMLAnchorElement>, route: RouteId) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    onNavigate(route);
  }

  return (
    <>
      {items.map((item) => {
        const showSection = item.section !== lastSection;
        lastSection = item.section;
        const Icon = iconByKey[item.icon];
        const active = item.route === activeRoute || item.children?.some((child) => child.route === activeRoute) === true;
        const expanded = item.children ? expandedGroup === item.id : false;
        const firstVisibleRoute = item.children?.[0]?.route ?? item.route;
        const childrenId = item.children ? `Prudentia-nav-${item.id}` : undefined;
        const dataFirst = firstButton ? { "data-sidebar-first": "true" } : {};
        const content = (
          <>
            <Icon size={16} aria-hidden="true" />
            <span className="Prudentia-nav-label">{item.label}</span>
            <NavigationBadgeCount badge={item.badge} count={badgeValue(item.badge)} />
            {item.children ? expanded ? <ChevronDown aria-hidden="true" className="Prudentia-nav-chevron" size={13} /> : <ChevronRight aria-hidden="true" className="Prudentia-nav-chevron" size={13} /> : null}
          </>
        );
        firstButton = false;
        return (
          <div key={item.id} className="Prudentia-nav-group">
            {showSection ? <p className="Prudentia-sidebar-section">{item.section}</p> : null}
            {item.children ? (
              <button
                {...dataFirst}
                type="button"
                onClick={() => {
                  if (!sidebarCollapsed) {
                    onExpand(expanded ? null : item.id);
                    return;
                  }
                  if (firstVisibleRoute) onNavigate(firstVisibleRoute);
                }}
                className={active ? "Prudentia-sidenav-item-active" : "Prudentia-sidenav-item"}
                aria-controls={!sidebarCollapsed ? childrenId : undefined}
                aria-expanded={!sidebarCollapsed ? expanded : undefined}
                aria-label={item.label}
                title={item.label}
              >
                {content}
              </button>
            ) : firstVisibleRoute ? (
              <a
                {...dataFirst}
                href={routePaths[firstVisibleRoute]}
                onClick={(event) => navigate(event, firstVisibleRoute)}
                className={active ? "Prudentia-sidenav-item-active" : "Prudentia-sidenav-item"}
                aria-current={active ? "page" : undefined}
                aria-label={item.label}
                title={item.label}
              >
                {content}
              </a>
            ) : null}
            {item.children && expanded && !sidebarCollapsed ? (
              <div className="Prudentia-sidenav-children" id={childrenId}>
                {item.children.map((child) => {
                  const count = badgeValue(child.badge);
                  const childActive = child.route === activeRoute;
                  return (
                    <a
                      key={child.route}
                      href={routePaths[child.route]}
                      onClick={(event) => navigate(event, child.route)}
                      className={childActive ? "Prudentia-sidenav-child-active" : "Prudentia-sidenav-child"}
                      aria-current={childActive ? "page" : undefined}
                    >
                      <span>{child.label}</span>
                      <NavigationBadgeCount badge={child.badge} count={count} />
                    </a>
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

function NavigationBadgeCount({ badge, count }: { badge: NavigationBadge | undefined; count: number | null }) {
  if (count === null || count <= 0) return null;
  const label = badge === "review"
    ? `${count} documents require review`
    : `${count} deleted documents`;
  return <small aria-label={label}>{count > 99 ? "99+" : count}</small>;
}

interface SidebarMenuProps {
  activeRoute: RouteId;
  badgeValue: SidebarBadgeValue;
  expandedGroup: string | null;
  items: WorkspaceNavigationItem[];
  onExpand: (group: string | null) => void;
  onNavigate: (route: RouteId) => void;
  sidebarCollapsed: boolean;
}
