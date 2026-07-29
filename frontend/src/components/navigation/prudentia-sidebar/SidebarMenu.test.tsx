import { Children, isValidElement, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { RouteId } from "@/routes/routes";
import { SidebarMenu } from "./SidebarMenu";

const items = [{
  children: [{ label: "Workspace Summary", route: "overview" as const }],
  icon: "overview" as const,
  id: "overview",
  label: "System Overview",
  section: "Operate" as const,
}];

describe("SidebarMenu groups", () => {
  it("toggles expanded groups without navigating, but navigates from collapsed mode", () => {
    const onExpand = vi.fn();
    const onNavigate = vi.fn();

    topLevelButton({ expandedGroup: "overview", onExpand, onNavigate, sidebarCollapsed: false }).props.onClick();
    expect(onExpand).toHaveBeenCalledWith(null);
    expect(onNavigate).not.toHaveBeenCalled();

    topLevelButton({ expandedGroup: null, onExpand, onNavigate, sidebarCollapsed: true }).props.onClick();
    expect(onNavigate).toHaveBeenCalledWith("overview");
  });

  it("renders route destinations as links", () => {
    const html = renderToStaticMarkup(<SidebarMenu
      activeRoute="chat"
      badgeValue={() => null}
      expandedGroup={null}
      items={[{ icon: "query", id: "query", label: "Query Intelligence", route: "chat", section: "Operate" }]}
      onExpand={vi.fn()}
      onNavigate={vi.fn()}
      sidebarCollapsed={false}
    />);

    expect(html).toContain('href="/chat"');
    expect(html).toContain('aria-current="page"');
  });

  it("describes Review Queue counts as documents requiring review", () => {
    const html = renderToStaticMarkup(<SidebarMenu
      activeRoute="chat"
      badgeValue={(badge) => badge === "review" ? 142 : null}
      expandedGroup={null}
      items={[{ badge: "review", icon: "review", id: "review", label: "Review Queue", route: "review", section: "Evaluate" }]}
      onExpand={vi.fn()}
      onNavigate={vi.fn()}
      sidebarCollapsed={false}
    />);

    expect(html).toContain('aria-label="142 documents require review"');
    expect(html).toContain("99+");
  });
});

function topLevelButton({ expandedGroup, onExpand, onNavigate, sidebarCollapsed }: {
  expandedGroup: string | null;
  onExpand: (group: string | null) => void;
  onNavigate: (route: RouteId) => void;
  sidebarCollapsed: boolean;
}): ReactElement<{ onClick: () => void }> {
  const menu = SidebarMenu({ activeRoute: "overview", badgeValue: () => null, expandedGroup, items, onExpand, onNavigate, sidebarCollapsed });
  const group = Children.toArray((menu.props as { children: ReactNode }).children)[0];
  if (!isValidElement<{ children: ReactNode }>(group)) throw new Error("Sidebar group not rendered");
  const button = Children.toArray(group.props.children).find((child) => isValidElement(child) && child.type === "button");
  if (!isValidElement<{ onClick: () => void }>(button)) throw new Error("Sidebar group button not rendered");
  return button;
}
