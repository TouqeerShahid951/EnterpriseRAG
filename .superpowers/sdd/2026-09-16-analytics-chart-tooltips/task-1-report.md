# Task 1 report: deterministic analytics value formatting

## Files changed

- `frontend/src/features/analytics/components/AnalyticsCharts.tsx`
  - Added the pure exported `formatAnalyticsChartValue` formatter.
  - Applied it to line-chart accessible table values.
- `frontend/src/features/analytics/components/AnalyticsCharts.test.tsx`
  - Added the required formatter behavior test.

The report file is also created as explicitly requested. Other pre-existing user changes were not staged or modified.

## Commits

- `6e82a7c` — `test: define analytics chart value formatting`

## Test commands and results

- `npm --prefix frontend test -- --run src/features/analytics/components/AnalyticsCharts.test.tsx`
  - PASS: 1 test file, 3 tests.
- `npm --prefix frontend test`
  - PASS: 80 test files, 346 tests.

## RED/GREEN evidence

### RED

After adding the formatter test and before implementation:

`npm --prefix frontend test -- --run src/features/analytics/components/AnalyticsCharts.test.tsx`

Failed as expected: 1 failed, 2 passed. The failure was `TypeError: formatAnalyticsChartValue is not a function`.

### GREEN

After the minimal implementation:

The focused test passed with 3/3 tests, followed by the full frontend suite passing with 80/80 files and 346/346 tests.

## Self-review

- Formatter is pure and colocated with analytics chart vocabulary.
- `null` returns `Unavailable`.
- `count` uses grouped integer formatting.
- `ms` rounds with `Math.round` before grouped formatting.
- Other units use `en-US` grouping with at most two decimal places and retain the supplied unit.
- Only the two requested code/test files were committed.

## Concerns

- No tooltip builder exists in the current target component; this task exposes the shared formatter and uses it for accessible output. Future tooltip builders should call the same function.
- The formatter assumes numeric inputs are finite, matching the typed interface and existing chart data contract.

## Follow-up fix: stacked outcome accessible values

The stacked outcome chart's visually hidden table was still rendering raw numeric cells without the `count` unit. Fixed `AnalyticsOutcomeChart` to call `formatAnalyticsChartValue(bucket[key], "count")`, matching the line-chart accessible values.

### Follow-up RED

Added an assertion requiring the outcome table to contain `>1 count<`. The focused analytics test failed as expected: 1 failed, 2 passed, because the rendered outcome cell was `1`.

### Follow-up GREEN

After the minimal implementation, `npm --prefix frontend test -- --run src/features/analytics/components/AnalyticsCharts.test.tsx` passed with 3/3 tests, and `npm --prefix frontend test` passed with 80/80 test files and 346/346 tests.
