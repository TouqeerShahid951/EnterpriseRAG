import { useEffect, useState } from "react";

import { analyticsUrl, changeAnalyticsState, readAnalyticsState, type AnalyticsState } from "./analyticsPageState";

export function useAnalyticsPageState() {
  const [state, setState] = useState(() => readAnalyticsState(typeof window === "undefined" ? "" : window.location.search));

  function change(patch: Partial<AnalyticsState>) {
    const next = changeAnalyticsState(state, patch);
    const url = analyticsUrl(new URL(window.location.href), next);
    if (url !== `${window.location.pathname}${window.location.search}${window.location.hash}`) {
      window.history.pushState(window.history.state, "", url);
    }
    setState(next);
  }

  function refresh() {
    setState((current) => ({ ...current, asOf: new Date().toISOString(), offset: 0 }));
  }

  useEffect(() => {
    window.history.replaceState(window.history.state, "", analyticsUrl(new URL(window.location.href), state));
  }, [state]);

  useEffect(() => {
    const restore = () => setState(readAnalyticsState(window.location.search));
    window.addEventListener("popstate", restore);
    return () => window.removeEventListener("popstate", restore);
  }, []);

  useEffect(() => {
    // Keep a fixed snapshot while paging or investigating a historical execution.
    if (state.offset || state.drilldown || state.selectedExecutionId) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") refresh();
    }, 30000);
    return () => window.clearInterval(timer);
  }, [state.offset, state.drilldown, state.selectedExecutionId]);

  return { state, change, refresh };
}
