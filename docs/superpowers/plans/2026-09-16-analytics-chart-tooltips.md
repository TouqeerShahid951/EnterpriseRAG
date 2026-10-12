# Analytics Chart Tooltips Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show exact analytics values in a consistent tooltip for every existing line and stacked-bar chart on hover and keyboard focus without changing analytics data contracts or bucket filtering.

**Architecture:** Extend the existing feature-owned SVG renderers in `AnalyticsCharts.tsx`. Each chart keeps one local active bucket, renders one HTML tooltip anchored to that bucket, and exposes the same values through the bucket’s accessible label; the existing screen-reader tables remain the complete fallback. No chart library, API change, or unused pie-chart implementation is added.

**Tech Stack:** React 18, TypeScript, custom SVG, existing analytics CSS, Vitest static-markup tests.

**Spec:** Bounded in-chat design from the 2026-09-16 user request; no separate design spec is needed for this existing feature flow.

## Global Constraints

- Preserve `select a bucket to filter the table` click and Enter/Space behavior.
- Show the bucket label and exact formatted values on pointer hover and keyboard focus.
- Keep the existing visually hidden data tables; do not make color the only way to identify a series or outcome.
- Use existing semantic theme tokens so the tooltip remains readable in light and dark mode.
- Do not add a chart dependency or backend/API fields.
- The current analytics feature has line and stacked-bar charts only; do not add speculative pie-chart code.
- Preserve unrelated dirty worktree changes and stage only files in this plan if commits are made.

---

### Task 1: Add deterministic analytics value formatting

**Files:**

- Modify: `frontend/src/features/analytics/components/AnalyticsCharts.tsx:1-29`
- Test: `frontend/src/features/analytics/components/AnalyticsCharts.test.tsx:1-5`

**Interfaces:**

- Produces `formatAnalyticsChartValue(value: number | null, unit: string): string`, used by both tooltip builders and accessible labels.
- `null` values render as `Unavailable`.
- `count` values use grouped integer formatting and the `count` unit.
- `ms` values use the existing rounded-millisecond presentation and the `ms` unit.
- Other numeric units, including `0–1 score`, use locale grouping with at most two decimal places and retain the supplied unit.

- [ ] **Step 1: Write the failing formatter tests.**

```tsx
import { formatAnalyticsChartValue } from "./AnalyticsCharts";

it("formats chart values consistently for tooltip and accessible output", () => {
  expect(formatAnalyticsChartValue(5, "count")).toBe("5 count");
  expect(formatAnalyticsChartValue(20333.4, "ms")).toBe("20,333 ms");
  expect(formatAnalyticsChartValue(0.8123, "0–1 score")).toBe("0.81 0–1 score");
  expect(formatAnalyticsChartValue(null, "ms")).toBe("Unavailable");
});
```

- [ ] **Step 2: Run the focused test and verify it fails because the formatter is not implemented.**

Run: `npm --prefix frontend test -- --run src/features/analytics/components/AnalyticsCharts.test.tsx`

Expected: FAIL with the missing `formatAnalyticsChartValue` export or equivalent missing implementation error.

- [ ] **Step 3: Implement the formatter in `AnalyticsCharts.tsx`.**

Use `toLocaleString("en-US")` for grouped values, `Math.round` for milliseconds, and `maximumFractionDigits: 2` for non-integer metrics. Keep the function pure and colocated with the chart data vocabulary.

- [ ] **Step 4: Run the focused test and verify it passes.**

Run: `npm --prefix frontend test -- --run src/features/analytics/components/AnalyticsCharts.test.tsx`

Expected: PASS, including all existing analytics chart tests.

- [ ] **Step 5: Commit only the formatter and test changes.**

```bash
git add frontend/src/features/analytics/components/AnalyticsCharts.tsx frontend/src/features/analytics/components/AnalyticsCharts.test.tsx
git commit -m "test: define analytics chart value formatting"
```

### Task 2: Add hover and focus tooltips to every analytics chart renderer

**Files:**

- Modify: `frontend/src/features/analytics/components/AnalyticsCharts.tsx:30-103`
- Test: `frontend/src/features/analytics/components/AnalyticsCharts.test.tsx:7-47`

**Interfaces:**

- `ChartTooltipItem` contains `{ label: string; value: string }`.
- `ChartTooltip` contains `{ title: string; items: ChartTooltipItem[]; index: number }`.
- `ChartAxes` receives `tooltip: ChartTooltip | null` and a stable `tooltipId`, then renders the shared tooltip markup.
- `AnalyticsLineChart` builds one tooltip per bucket containing every supplied line metric, including `Unavailable` for null metrics.
- `AnalyticsOutcomeChart` builds one tooltip per bucket containing the total and all outcome categories.

- [ ] **Step 1: Add failing accessibility/rendering assertions for exact bucket values.**

Define one shared `tooltipBucket` fixture immediately before these tests, then add assertions for a bucket containing multiple series and outcomes:

```tsx
const tooltipBucket = {
    started_at: "2026-09-08T00:00:00Z",
    ended_at: "2026-09-09T00:00:00Z",
    total_executions: 5,
    p50_latency_ms: 12000,
    p95_latency_ms: 20333.4,
    complete: 3,
    partial: 2,
    clarification: 0,
    abstained: 0,
    system_error: 0,
    access_denied: 0,
    cancelled: 0,
    interrupted: 0,
    artifact_submitted: 0,
} as AnalyticsSeriesBucket;

it("exposes exact line values on each bucket control", () => {

  const markup = renderToStaticMarkup(
    <AnalyticsLineChart
      buckets={[tooltipBucket]}
      metrics={[
        { key: "total_executions", label: "Executions", tone: "accent", unit: "count" },
        { key: "p95_latency_ms", label: "P95", tone: "warning", unit: "ms" },
      ]}
      onBucketSelect={() => undefined}
    />,
  );

  expect(markup).toContain("Executions 5 count");
  expect(markup).toContain("P95 20,333 ms");
  expect(markup).not.toContain('aria-hidden="true"');
});

it("exposes total and category values on each stacked-bar bucket", () => {
  const markup = renderToStaticMarkup(<AnalyticsOutcomeChart buckets={[tooltipBucket]} onBucketSelect={() => undefined} />);

  expect(markup).toContain("Total 5 count");
  expect(markup).toContain("Complete 3 count");
  expect(markup).toContain("Partial 2 count");
});
```

Update the existing keyboard assertion in the same test file to expect the chart group label without the removed `aria-hidden` attribute.

- [ ] **Step 2: Run the focused tests and verify the new assertions fail.**

Run: `npm --prefix frontend test -- --run src/features/analytics/components/AnalyticsCharts.test.tsx`

Expected: FAIL because bucket controls do not yet expose the tooltip values.

- [ ] **Step 3: Add the shared tooltip state and markup.**

In `AnalyticsCharts.tsx`:

1. Import `useId` and `useState` from React.
2. Add a local `formatAnalyticsBucketLabel(startedAt, hourly)` helper using UTC-only formatting. Day buckets should read like `Sep 8, 2026 UTC`; hourly buckets should include the UTC time.
3. Update `ChartAxes` to render a `div.analytics-chart-tooltip` with `role="tooltip"`, the bucket title, and one labeled value row per item when `tooltip` is active. Position it with the existing `x` coordinate converted to a clamped percentage so first and last buckets do not clip.
4. Give each chart a `useState<number | null>` active index and `useId()` tooltip id.
5. On every bucket hit area, set the active index on `onPointerEnter`/`onFocus` and clear it on `onPointerLeave`/`onBlur`. Add `aria-describedby` while the matching tooltip is active.
6. Replace the bucket-only accessible label with a label containing the UTC bucket and every formatted metric/category value. Append the existing filter action text when `onBucketSelect` is present.
7. Keep the current `onClick` and Enter/Space selection behavior unchanged. The tooltip is informational; it must not make the tooltip itself clickable or intercept pointer events.
8. Remove the conditional `aria-hidden` from the SVG because the focusable bucket controls now carry the chart values even when no selection callback is supplied. Use `role="button"` when a bucket-selection callback exists and `role="img"` otherwise.

- [ ] **Step 4: Implement the line-chart tooltip data.**

For the active bucket, map `metrics` to `{ label: metric.label, value: formatAnalyticsChartValue(valueFor(bucket, metric.key), metric.unit) }`. Keep null latency/faithfulness values visible as `Unavailable` rather than dropping them.

- [ ] **Step 5: Implement the stacked-bar tooltip data.**

For the active bucket, include `{ label: "Total", value: formatAnalyticsChartValue(outcomeTotal(bucket), "count") }` followed by every `outcomeMetrics` entry using its exact bucket count. Keep zero-valued categories so the tooltip is a complete breakdown and does not depend on the segment color.

- [ ] **Step 6: Run the focused tests and verify they pass.**

Run: `npm --prefix frontend test -- --run src/features/analytics/components/AnalyticsCharts.test.tsx`

Expected: PASS, including the original keyboard drill-down and axis/date tests plus the new exact-value assertions.

- [ ] **Step 7: Commit only the chart component and its tests.**

```bash
git add frontend/src/features/analytics/components/AnalyticsCharts.tsx frontend/src/features/analytics/components/AnalyticsCharts.test.tsx
git commit -m "feat: add analytics chart value tooltips"
```

### Task 3: Style the tooltip for both themes and verify the page behavior

**Files:**

- Modify: `frontend/src/styles/analytics-dashboard.css:67-101`

**Interfaces:**

- `.analytics-chart-data` becomes the positioning context for the tooltip.
- `.analytics-chart-tooltip` uses existing surface, foreground, border, and shadow tokens; no raw light/dark colors are introduced.
- `.analytics-chart-tooltip` has `pointer-events: none`, readable spacing, a bounded width, and enough stacking order to sit above the SVG without blocking it.
- Focus-visible bucket controls retain a visible outline and background in light and dark mode.

- [ ] **Step 1: Add the minimal theme-safe tooltip styles.**

Add `position: relative` to `.analytics-chart-data`. Add a compact absolute tooltip with `background: var(--color-surface-card)`, `color: var(--color-on-surface)`, `border: 1px solid var(--color-surface-border)`, existing spacing scale values, and `pointer-events: none`. Style the title and rows using the current analytics type scale. Add `:focus-visible` styling to the SVG hit areas without removing the existing focus behavior.

- [ ] **Step 2: Run the analytics tests and typecheck.**

Run: `npm --prefix frontend test -- --run src/features/analytics/components/AnalyticsCharts.test.tsx`

Run: `npm --prefix frontend run typecheck`

Expected: both commands pass.

- [ ] **Step 3: Verify the actual page in both themes.**

Open `/operational-analytics` and check:

1. Hover a Query volume point/bucket: the tooltip shows the UTC bucket and executions count.
2. Hover P50/P95 latency buckets: both series appear with `ms` values, including missing data as `Unavailable`.
3. Hover an Outcome distribution bucket: total and every category count appear.
4. Focus each chart bucket with Tab: the same tooltip appears and the focus indicator is visible; Enter/Space still opens the filtered query list.
5. Repeat in light and dark themes and at a narrow viewport; the tooltip text remains readable and does not clip at the first or last bucket.
6. Confirm the hidden tables still provide the complete values and no console errors are emitted.

- [ ] **Step 4: Run the broader frontend verification.**

Run: `npm --prefix frontend test`

Run: `npm --prefix frontend run build`

Run: `npm --prefix frontend run check:dead-code`

Expected: tests, typecheck/build pass. If `check:dead-code` reports the repository’s existing baseline findings, record that it is unchanged and do not widen this slice.

- [ ] **Step 5: Commit the chart stylesheet only.**

```bash
git add frontend/src/styles/analytics-dashboard.css
git commit -m "style: make analytics chart tooltips theme safe"
```

## Self-review

- Line charts, the stacked outcome bar chart, and the quality trend all use the same tooltip behavior through `AnalyticsCharts.tsx`.
- Existing click and keyboard bucket filtering remains intact.
- Hover-only data is paired with focus behavior, accessible labels, and the existing data tables.
- No pie-chart code is added because no pie chart currently exists in the feature; a future pie renderer should supply category/value/percentage items to the same tooltip markup.
- No backend, API, route, dependency, or unrelated theme files are touched.
