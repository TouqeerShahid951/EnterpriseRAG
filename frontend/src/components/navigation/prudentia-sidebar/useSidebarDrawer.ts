import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent, RefObject } from "react";

import type { RouteId } from "@/routes/routes";

export interface SidebarDrawerController {
  closeAndRestoreFocus: () => void;
  dismiss: () => void;
  drawerRef: RefObject<HTMLElement>;
  mobileOpen: boolean;
  onKeyDown: (event: KeyboardEvent<HTMLElement>) => void;
  open: () => void;
  triggerRef: RefObject<HTMLButtonElement>;
}

export function useSidebarDrawer(activeRoute: RouteId): SidebarDrawerController {
  const [mobileOpen, setMobileOpen] = useState(false);
  const drawerRef = useRef<HTMLElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    setMobileOpen(false);
  }, [activeRoute]);

  useEffect(() => {
    document.body.classList.toggle("Prudentia-mobile-nav-open", mobileOpen);
    if (mobileOpen) {
      requestAnimationFrame(() => drawerRef.current?.querySelector<HTMLElement>("[data-sidebar-first='true']")?.focus());
    }
    return () => document.body.classList.remove("Prudentia-mobile-nav-open");
  }, [mobileOpen]);

  function closeAndRestoreFocus() {
    setMobileOpen(false);
    triggerRef.current?.focus();
  }

  function handleDrawerKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      closeAndRestoreFocus();
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

  return {
    closeAndRestoreFocus,
    dismiss: () => setMobileOpen(false),
    drawerRef,
    mobileOpen,
    onKeyDown: handleDrawerKeyDown,
    open: () => setMobileOpen(true),
    triggerRef,
  };
}
