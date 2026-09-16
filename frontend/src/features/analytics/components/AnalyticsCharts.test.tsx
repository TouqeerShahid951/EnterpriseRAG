import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";

import type { AnalyticsSeriesBucket } from "@/types/api";
import { AnalyticsLineChart, AnalyticsOutcomeChart, formatAnalyticsChartValue } from "./AnalyticsCharts";

it("formats chart values consistently for tooltip and accessible output", () => {
  expect(formatAnalyticsChartValue(5, "count")).toBe("5 count");
  expect(formatAnalyticsChartValue(20333.4, "ms")).toBe("20,333 ms");
  expect(formatAnalyticsChartValue(0.8123, "0–1 score")).toBe("0.81 0–1 score");
  expect(formatAnalyticsChartValue(null, "ms")).toBe("Unavailable");
});

it("keeps keyboard drill-down controls in the accessibility tree", () => {
  const buckets = [{ started_at: "2026-09-09T00:00:00Z", total_executions: 1, complete: 1,
    partial: 0, clarification: 0, abstained: 0, system_error: 0, access_denied: 0,
    cancelled: 0, interrupted: 0, artifact_submitted: 0 }] as AnalyticsSeriesBucket[];
  for (const chart of [
    <AnalyticsLineChart buckets={buckets} metrics={[{ key: "total_executions", label: "Executions", tone: "accent", unit: "count" }]} onBucketSelect={() => {}} />,
    <AnalyticsOutcomeChart buckets={buckets} onBucketSelect={() => {}} />,
  ]) {
    const markup = renderToStaticMarkup(chart);
    expect(markup).toContain('role="group" aria-label="Filter executions by UTC bucket" aria-hidden="false"');
    expect(markup).toContain('role="button" tabindex="0" aria-label="Filter executions to 2026-09-09T00:00:00Z UTC bucket"');
  }
});

it("renders visible UTC dates, numeric ticks and units for every trend", () => {
  const bucket = { started_at: "2026-09-08T00:00:00Z", ended_at: "2026-09-09T00:00:00Z", total_executions: 1, complete: 1,
    partial: 0, clarification: 0, abstained: 0, system_error: 0, access_denied: 0,
    cancelled: 0, interrupted: 0, artifact_submitted: 0, p50_latency_ms: 20000,
    p95_latency_ms: 40000, faithfulness_score_mean: 0.8 } as AnalyticsSeriesBucket;
  for (const [chart, label, midpoint] of [
    [<AnalyticsLineChart buckets={[bucket]} metrics={[{ key: "total_executions", label: "Executions", tone: "accent", unit: "count" }]} />, "Executions (count)", "1"],
    [<AnalyticsOutcomeChart buckets={[bucket]} />, "Executions (count)", "1"],
    [<AnalyticsLineChart buckets={[bucket]} metrics={[{ key: "p95_latency_ms", label: "P95", tone: "warning", unit: "ms" }]} />, "Latency (ms)", "20,000"],
    [<AnalyticsLineChart buckets={[bucket]} metrics={[{ key: "faithfulness_score_mean", label: "Score", tone: "accent", unit: "0–1 score" }]} />, "Mean checked score (0–1)", "0.5"],
  ] as const) {
    const visibleChart = renderToStaticMarkup(chart).split("<table")[0];
    expect(visibleChart).toContain(label);
    expect(visibleChart).toContain(`>${midpoint}</span>`);
    expect(visibleChart).toContain(">Sep 8</time>");
    expect(visibleChart).toContain("Date (UTC)");
    expect(visibleChart).not.toMatch(/NaN|Infinity/);
  }

  const hourly = renderToStaticMarkup(<AnalyticsOutcomeChart buckets={[
    { ...bucket, started_at: "2026-09-08T23:00:00Z", ended_at: "2026-09-09T00:00:00Z" },
    { ...bucket, started_at: "2026-09-09T00:00:00Z", ended_at: "2026-09-09T01:00:00Z" },
  ]} />).split("<table")[0];
  expect(hourly).toContain("Sep 8<span>23:00</span>");
  expect(hourly).toContain("Sep 9<span>00:00</span>");
  expect(hourly).toContain("Date / time (UTC)");
});
