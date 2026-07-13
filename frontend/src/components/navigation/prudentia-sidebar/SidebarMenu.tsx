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

import type { NavigationIcon, RouteId, WorkspaceNavigationItem } from "@/routes/routes";
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
          <div key={item.id} className="Prudentia-nav-group">
            {showSection ? <p className="Prudentia-sidebar-section">{item.section}</p> : null}
            <button
              {...dataFirst}
              type="button"
              onClick={() => {
                if (item.children) onExpand(item.id);
                if (firstVisibleRoute) onNavigate(firstVisibleRoute);
              }}
              className={active ? "Prudentia-sidenav-item-active" : "Prudentia-sidenav-item"}
              aria-current={!item.children && active ? "page" : undefined}
              aria-expanded={item.children && !sidebarCollapsed ? expanded : undefined}
              aria-label={item.label}
              title={item.label}
            >
              <Icon size={16} aria-hidden="true" />
              <span className="Prudentia-nav-label">{item.label}</span>
              <NavigationBadgeCount count={badgeValue(item.badge)} />
              {item.children ? expanded ? <ChevronDown className="Prudentia-nav-chevron" size={13} /> : <ChevronRight className="Prudentia-nav-chevron" size={13} /> : null}
            </button>
            {item.children && expanded && !sidebarCollapsed ? (
              <div className="Prudentia-sidenav-children">
                {item.children.map((child) => {
                  const count = badgeValue(child.badge);
                  const childActive = child.route === activeRoute;
                  return (
                    <button
                      key={child.route}
                      type="button"
                      onClick={() => onNavigate(child.route)}
                      className={childActive ? "Prudentia-sidenav-child-active" : "Prudentia-sidenav-child"}
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

interface SidebarMenuProps {
  activeRoute: RouteId;
  badgeValue: SidebarBadgeValue;
  expandedGroup: string | null;
  items: WorkspaceNavigationItem[];
  onExpand: (group: string) => void;
  onNavigate: (route: RouteId) => void;
  sidebarCollapsed: boolean;
}
