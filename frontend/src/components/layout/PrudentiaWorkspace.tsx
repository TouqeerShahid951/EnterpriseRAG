import {
  createContext,
  useContext,
  useEffect,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";

import {
  Prudentia_SIDEBAR_COLLAPSED_WIDTH,
  Prudentia_SIDEBAR_MAX_WIDTH,
  Prudentia_SIDEBAR_MIN_WIDTH,
  PrudentiaSidebar,
  getPrudentiaSidebarDefaultWidth,
} from "@/components/navigation/PrudentiaSidebar";
import type { RouteId } from "@/routes/routes";
import { readStoredBoolean, readStoredNumber, writeStoredBoolean, writeStoredNumber } from "@/lib/utils/uiPreferences";
import type { User as AuthUser } from "@/types/api";

const SIDEBAR_COLLAPSED_STORAGE_KEY = "Prudentia-sidebar-collapsed";
const SIDEBAR_WIDTH_STORAGE_KEY = "Prudentia-sidebar-width-comfortable-v4";

const SidebarHeaderContext = createContext<SidebarChromeContext>({
  headerContent: null,
  isLightMode: false,
});

export function PrudentiaSidebarHeaderProvider({ children, isLightMode, onToggleTheme, value }: SidebarHeaderProviderProps) {
  return (
    <SidebarHeaderContext.Provider value={{ headerContent: value, isLightMode, onToggleTheme }}>
      {children}
    </SidebarHeaderContext.Provider>
  );
}

export function PrudentiaWorkspace({ activeRoute, children, onLogout, onNavigate, sidebarHeaderContent, user }: Props) {
  const sidebarChrome = useContext(SidebarHeaderContext);
  const [sidebarWidth, setSidebarWidth] = useState(readStoredSidebarWidth);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => readStoredBoolean(SIDEBAR_COLLAPSED_STORAGE_KEY, false));
  const headerContent = sidebarHeaderContent !== undefined ? sidebarHeaderContent : sidebarChrome.headerContent;
  const visibleSidebarWidth = sidebarCollapsed ? Prudentia_SIDEBAR_COLLAPSED_WIDTH : sidebarWidth;

  useEffect(() => {
    writeStoredNumber(SIDEBAR_WIDTH_STORAGE_KEY, sidebarWidth);
  }, [sidebarWidth]);

  useEffect(() => {
    writeStoredBoolean(SIDEBAR_COLLAPSED_STORAGE_KEY, sidebarCollapsed);
  }, [sidebarCollapsed]);

  return (
    <div
      className={sidebarCollapsed ? "Prudentia-shell Prudentia-shell-sidebar-collapsed" : "Prudentia-shell"}
      data-route={activeRoute}
      style={{ "--sidebar-width": `${visibleSidebarWidth}px` } as CSSProperties}
    >
      <PrudentiaSidebar
        activeRoute={activeRoute}
        headerContent={headerContent}
        isLightMode={sidebarChrome.isLightMode}
        onLogout={onLogout}
        onNavigate={onNavigate}
        onSidebarCollapsedChange={setSidebarCollapsed}
        onSidebarWidthChange={setSidebarWidth}
        onToggleTheme={sidebarChrome.onToggleTheme}
        sidebarCollapsed={sidebarCollapsed}
        sidebarWidth={sidebarWidth}
        user={user}
      />
      <div className="Prudentia-main">{children}</div>
    </div>
  );
}

export function PrudentiaBasicPage({ activeRoute, children, onLogout, onNavigate, sidebarHeaderContent, subtitle, title, user }: BasicProps) {
  return (
    <PrudentiaWorkspace activeRoute={activeRoute} onLogout={onLogout} onNavigate={onNavigate} sidebarHeaderContent={sidebarHeaderContent} user={user}>
      <main className="sv-page" id="main-content">
        <div className={`sv-page-inner ${pageInnerModeClass(activeRoute)}`}>
          <header className="sv-page-header">
            <div>
              <p className="sv-eyebrow">Prudentia AI</p>
              <h1 className="sv-page-title">{title}</h1>
              <p className="sv-page-subtitle">{subtitle}</p>
            </div>
          </header>
          {children}
        </div>
      </main>
    </PrudentiaWorkspace>
  );
}

type Props = {
  activeRoute: RouteId;
  children: ReactNode;
  onLogout?: () => void;
  onNavigate: (route: RouteId) => void;
  sidebarHeaderContent?: ReactNode;
  user: AuthUser;
};

type SidebarHeaderProviderProps = {
  children: ReactNode;
  isLightMode: boolean;
  onToggleTheme: () => void;
  value: ReactNode;
};

type SidebarChromeContext = {
  headerContent: ReactNode;
  isLightMode: boolean;
  onToggleTheme?: () => void;
};

type BasicProps = Props & {
  subtitle: string;
  title: string;
};

function pageInnerModeClass(route: RouteId): string {
  if (route === "access") return "sv-page-inner-workbench";
  if (route === "overview") return "sv-page-inner-dashboard";
  if (route === "settings" || route === "account") return "sv-page-inner-form";
  return "";
}

function readStoredSidebarWidth(): number {
  const viewportWidth = typeof window === "undefined" ? 0 : window.innerWidth;
  return readStoredNumber(SIDEBAR_WIDTH_STORAGE_KEY, {
    fallback: getPrudentiaSidebarDefaultWidth(viewportWidth),
    max: Prudentia_SIDEBAR_MAX_WIDTH,
    min: Prudentia_SIDEBAR_MIN_WIDTH,
  });
}
