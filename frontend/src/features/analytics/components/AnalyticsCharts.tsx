import type { ReactNode } from "react";

import type { AnalyticsSeriesBucket } from "@/types/api";

type LineMetric = {
  key: "total_executions" | "p50_latency_ms" | "p95_latency_ms" | "faithfulness_score_mean";
  label: string;
  tone: "accent" | "secondary" | "warning";
  unit: string;
};

const outcomeMetrics = [
  ["complete", "Complete", "success"],
  ["partial", "Partial", "warning"],
  ["clarification", "Clarification", "muted"],
  ["abstained", "Abstained", "warning"],
  ["system_error", "System error", "danger"],
  ["access_denied", "Access denied", "danger"],
  ["cancelled", "Cancelled", "muted"],
  ["interrupted", "Interrupted", "muted"],
  ["artifact_submitted", "Artifact submitted", "muted"],
] as const;

const width = 600;
const height = 180;
const plot = { left: 12, right: 12, top: 12, bottom: 12 };
const plotHeight = height - plot.top - plot.bottom;
const yPosition = (value: number, max: number) => height - plot.bottom - value / max * plotHeight;

export function formatAnalyticsChartValue(value: number | null, unit: string): string {
  if (value === null) return "Unavailable";
  const formatted = (unit === "ms" ? Math.round(value) : value).toLocaleString("en-US", unit === "count" ? { maximumFractionDigits: 0 } : { maximumFractionDigits: 2 });
  return `${formatted} ${unit}`;
}

function ChartAxes({ buckets, max, x, label, children }: { buckets: AnalyticsSeriesBucket[]; max: number; x: (index: number) => number; label: string; children: ReactNode }) {
  const indices = [...new Set([0, Math.floor((buckets.length - 1) / 2), buckets.length - 1])].filter((index) => index >= 0 && index < buckets.length);
  const hourly = buckets.some((bucket) => Date.parse(bucket.ended_at) - Date.parse(bucket.started_at) <= 3600000);
  return <div className="analytics-chart-axes">
    <p className="analytics-axis-title">{label}</p>
    <div className="analytics-chart-plot">
      <div className="analytics-y-ticks">{[0, 0.5, 1].map((fraction) => <span key={fraction} style={{ top: `${yPosition(max * fraction, max) / height * 100}%` }}>{(max * fraction).toLocaleString("en-US", { maximumFractionDigits: 1 })}</span>)}</div>
      <div className="analytics-chart-data">
        {children}
        <div className="analytics-x-ticks">{indices.map((index, tick) => <time key={index} dateTime={buckets[index].started_at} style={{ left: `${x(index) / width * 100}%` }} data-align={tick === 0 ? "start" : tick === indices.length - 1 ? "end" : "middle"}>
          {new Date(buckets[index].started_at).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" })}
          {hourly ? <span>{new Date(buckets[index].started_at).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "UTC" })}</span> : null}
        </time>)}</div>
        <p className="analytics-axis-title analytics-x-title">{hourly ? "Date / time (UTC)" : "Date (UTC)"}</p>
      </div>
    </div>
  </div>;
}

export function AnalyticsLineChart({ buckets, metrics, onBucketSelect }: { buckets: AnalyticsSeriesBucket[]; metrics: LineMetric[]; onBucketSelect?: (bucket: AnalyticsSeriesBucket) => void }) {
  const peak = Math.max(1, ...metrics.flatMap((metric) => buckets.map((bucket) => valueFor(bucket, metric.key) ?? 0)));
  const max = metrics[0].key === "total_executions" ? Math.ceil(peak / 2) * 2 : peak;
  const label = metrics[0].key === "total_executions" ? "Executions (count)" : metrics[0].key === "faithfulness_score_mean" ? "Mean checked score (0–1)" : "Latency (ms)";
  const x = (index: number) => plot.left + (index / Math.max(1, buckets.length - 1)) * (width - plot.left - plot.right);
  const y = (value: number) => yPosition(value, max);

  return <figure className="analytics-chart" aria-label={metrics.map((metric) => metric.label).join(" and ")}>
    <ChartAxes buckets={buckets} max={max} x={x} label={label}>
    <svg preserveAspectRatio="none" viewBox={`0 0 ${width} ${height}`} role="group" aria-label="Filter executions by UTC bucket" aria-hidden={!onBucketSelect}>
      {[0, 0.5, 1].map((fraction) => <line key={fraction} className="analytics-grid-line" x1={plot.left} x2={width - plot.right} y1={y(max * fraction)} y2={y(max * fraction)} />)}
      {metrics.map((metric) => <polyline key={metric.key} className={`analytics-chart-line analytics-chart-line-${metric.tone}`} points={buckets.flatMap((bucket, index) => { const value = valueFor(bucket, metric.key); return value === null ? [] : [`${x(index)},${y(value)}`]; }).join(" ")} />)}
      {onBucketSelect ? buckets.map((bucket, index) => <rect key={bucket.started_at} className="analytics-chart-hitarea" x={x(index) - 12} y={plot.top} width={24} height={height - plot.top - plot.bottom} role="button" tabIndex={0} aria-label={`Filter executions to ${bucket.started_at} UTC bucket`} onClick={() => onBucketSelect(bucket)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onBucketSelect(bucket); } }} />) : null}
    </svg>
    </ChartAxes>
    <div className="analytics-chart-legend">{metrics.map((metric) => <span key={metric.key}><i className={`analytics-chart-swatch analytics-chart-swatch-${metric.tone}`} />{metric.label} ({metric.unit})</span>)}</div>
    <table className="sr-only"><caption>{metrics.map((metric) => metric.label).join(" and ")} by UTC bucket</caption><thead><tr><th scope="col">Bucket</th>{metrics.map((metric) => <th scope="col" key={metric.key}>{metric.label}</th>)}</tr></thead><tbody>{buckets.map((bucket) => <tr key={bucket.started_at}><th scope="row">{bucket.started_at}</th>{metrics.map((metric) => <td key={metric.key}>{formatAnalyticsChartValue(valueFor(bucket, metric.key), metric.unit)}</td>)}</tr>)}</tbody></table>
  </figure>;
}

export function AnalyticsOutcomeChart({ buckets, onBucketSelect }: { buckets: AnalyticsSeriesBucket[]; onBucketSelect?: (bucket: AnalyticsSeriesBucket) => void }) {
  const max = Math.ceil(Math.max(1, ...buckets.map((bucket) => outcomeTotal(bucket))) / 2) * 2;
  const x = (index: number) => plot.left + ((index + 0.5) / Math.max(1, buckets.length)) * (width - plot.left - plot.right);
  const barWidth = Math.max(2, (width - plot.left - plot.right) / Math.max(1, buckets.length) - 2);

  return <figure className="analytics-chart" aria-label="Query outcomes by UTC bucket">
    <ChartAxes buckets={buckets} max={max} x={x} label="Executions (count)">
    <svg preserveAspectRatio="none" viewBox={`0 0 ${width} ${height}`} role="group" aria-label="Filter executions by UTC bucket" aria-hidden={!onBucketSelect}>
      {[0, 0.5, 1].map((fraction) => <line key={fraction} className="analytics-grid-line" x1={plot.left} x2={width - plot.right} y1={height - plot.bottom - fraction * (height - plot.top - plot.bottom)} y2={height - plot.bottom - fraction * (height - plot.top - plot.bottom)} />)}
      {buckets.map((bucket, index) => {
        let offset = 0;
        const x = plot.left + (index / Math.max(1, buckets.length)) * (width - plot.left - plot.right) + 1;
        return outcomeMetrics.map(([key, , tone]) => {
          const value = bucket[key];
          const segmentHeight = value / max * (height - plot.top - plot.bottom);
          const rect = <rect key={`${bucket.started_at}-${key}`} className={`analytics-chart-segment analytics-chart-segment-${tone}`} x={x} y={height - plot.bottom - offset - segmentHeight} width={barWidth} height={segmentHeight} />;
          offset += segmentHeight;
          return rect;
        });
      })}
      {onBucketSelect ? buckets.map((bucket, index) => <rect key={`hit-${bucket.started_at}`} className="analytics-chart-hitarea" x={plot.left + (index / Math.max(1, buckets.length)) * (width - plot.left - plot.right)} y={plot.top} width={barWidth} height={height - plot.top - plot.bottom} role="button" tabIndex={0} aria-label={`Filter executions to ${bucket.started_at} UTC bucket`} onClick={() => onBucketSelect(bucket)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onBucketSelect(bucket); } }} />) : null}
    </svg>
    </ChartAxes>
    <div className="analytics-chart-legend">{outcomeMetrics.map(([, label, tone]) => <span key={label}><i className={`analytics-chart-swatch analytics-chart-swatch-${tone}`} />{label}</span>)}</div>
    <table className="sr-only"><caption>Query outcomes by UTC bucket</caption><thead><tr><th scope="col">Bucket</th>{outcomeMetrics.map(([, label]) => <th scope="col" key={label}>{label}</th>)}</tr></thead><tbody>{buckets.map((bucket) => <tr key={bucket.started_at}><th scope="row">{bucket.started_at}</th>{outcomeMetrics.map(([key]) => <td key={key}>{formatAnalyticsChartValue(bucket[key], "count")}</td>)}</tr>)}</tbody></table>
  </figure>;
}

function valueFor(bucket: AnalyticsSeriesBucket, key: LineMetric["key"]): number | null {
  return bucket[key];
}

function outcomeTotal(bucket: AnalyticsSeriesBucket) {
  return outcomeMetrics.reduce((total, [key]) => total + bucket[key], 0);
}
