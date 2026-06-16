import {
  createContext,
  useContext,
  useEffect,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";

import {
  FAHAM_SIDEBAR_DEFAULT_WIDTH,
  FAHAM_SIDEBAR_MAX_WIDTH,
  FAHAM_SIDEBAR_MIN_WIDTH,
  FahamSidebar,
} from "../navigation/FahamSidebar";
import type { RouteId } from "../../routes";
import type { User as AuthUser } from "../../types/api";

const SIDEBAR_WIDTH_STORAGE_KEY = "faham-sidebar-width";

const SidebarHeaderContext = createContext<SidebarChromeContext>({
  headerContent: null,
  isLightMode: false,
});

export function FahamSidebarHeaderProvider({ children, isLightMode, onToggleTheme, value }: SidebarHeaderProviderProps) {
  return (
    <SidebarHeaderContext.Provider value={{ headerContent: value, isLightMode, onToggleTheme }}>
      {children}
    </SidebarHeaderContext.Provider>
  );
}

export function FahamWorkspace({ activeRoute, children, onLogout, onNavigate, sidebarHeaderContent, user }: Props) {
  const sidebarChrome = useContext(SidebarHeaderContext);
  const [sidebarWidth, setSidebarWidth] = useState(readStoredSidebarWidth);
  const headerContent = sidebarHeaderContent !== undefined ? sidebarHeaderContent : sidebarChrome.headerContent;

  useEffect(() => {
    try {
      window.localStorage.setItem(SIDEBAR_WIDTH_STORAGE_KEY, String(sidebarWidth));
    } catch {
      // Sidebar resizing still works for the current session when storage is unavailable.
    }
  }, [sidebarWidth]);

  return (
    <div
      className="faham-shell"
      onPointerMove={updateCursorGlow}
      style={{ "--sidebar-width": `${sidebarWidth}px` } as CSSProperties}
    >
      <FahamSidebar
        activeRoute={activeRoute}
        headerContent={headerContent}
        isLightMode={sidebarChrome.isLightMode}
        onLogout={onLogout}
        onNavigate={onNavigate}
        onSidebarWidthChange={setSidebarWidth}
        onToggleTheme={sidebarChrome.onToggleTheme}
        sidebarWidth={sidebarWidth}
        user={user}
      />
      <div className="faham-main">{children}</div>
    </div>
  );
}

export function FahamBasicPage({ activeRoute, children, onLogout, onNavigate, sidebarHeaderContent, subtitle, title, user }: BasicProps) {
  return (
    <FahamWorkspace activeRoute={activeRoute} onLogout={onLogout} onNavigate={onNavigate} sidebarHeaderContent={sidebarHeaderContent} user={user}>
      <main className="sv-page" id="main-content">
        <div className="sv-page-inner">
          <header className="sv-page-header">
            <div>
              <p className="sv-eyebrow">Faham AI</p>
              <h1 className="sv-page-title">{title}</h1>
              <p className="sv-page-subtitle">{subtitle}</p>
            </div>
          </header>
          {children}
        </div>
      </main>
    </FahamWorkspace>
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

function readStoredSidebarWidth(): number {
  try {
    const storedWidth = Number(window.localStorage.getItem(SIDEBAR_WIDTH_STORAGE_KEY));
    if (!Number.isFinite(storedWidth)) return FAHAM_SIDEBAR_DEFAULT_WIDTH;
    return Math.min(FAHAM_SIDEBAR_MAX_WIDTH, Math.max(FAHAM_SIDEBAR_MIN_WIDTH, storedWidth));
  } catch {
    return FAHAM_SIDEBAR_DEFAULT_WIDTH;
  }
}

function updateCursorGlow(event: ReactPointerEvent<HTMLDivElement>) {
  if (event.pointerType === "touch") return;
  const target = event.target instanceof Element
    ? event.target.closest<HTMLElement>("[data-cursor-glow]")
    : null;
  if (!target || !event.currentTarget.contains(target)) return;
  const bounds = target.getBoundingClientRect();
  target.style.setProperty("--cursor-x", `${event.clientX - bounds.left}px`);
  target.style.setProperty("--cursor-y", `${event.clientY - bounds.top}px`);
}
