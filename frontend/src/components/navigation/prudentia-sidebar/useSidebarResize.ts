import type { KeyboardEvent, PointerEvent } from "react";

export const Prudentia_SIDEBAR_MIN_WIDTH = 216;
export const Prudentia_SIDEBAR_MAX_WIDTH = 336;
const Prudentia_SIDEBAR_DEFAULT_WIDTH = 224;
export const Prudentia_SIDEBAR_COLLAPSED_WIDTH = 64;

export interface SidebarResizeController {
  onKeyDown: (event: KeyboardEvent<HTMLDivElement>) => void;
  onPointerDown: (event: PointerEvent<HTMLDivElement>) => void;
}

export function getPrudentiaSidebarDefaultWidth(viewportWidth: number): number {
  if (viewportWidth >= 2400) return 272;
  if (viewportWidth >= 1680) return 256;
  if (viewportWidth >= 1440) return 240;
  return Prudentia_SIDEBAR_DEFAULT_WIDTH;
}

export function useSidebarResize({
  onSidebarWidthChange,
  sidebarCollapsed,
  sidebarWidth,
}: {
  onSidebarWidthChange: (width: number) => void;
  sidebarCollapsed: boolean;
  sidebarWidth: number;
}): SidebarResizeController {
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
    else if (event.key === "Home") onSidebarWidthChange(Prudentia_SIDEBAR_MIN_WIDTH);
    else if (event.key === "End") onSidebarWidthChange(Prudentia_SIDEBAR_MAX_WIDTH);
    else return;
    event.preventDefault();
  }

  return { onKeyDown: handleResizeKeyDown, onPointerDown: handleResizeStart };
}

function clampSidebarWidth(width: number): number {
  return Math.min(Prudentia_SIDEBAR_MAX_WIDTH, Math.max(Prudentia_SIDEBAR_MIN_WIDTH, width));
}
