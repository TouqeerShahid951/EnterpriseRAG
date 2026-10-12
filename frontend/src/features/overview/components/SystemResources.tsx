import { useQuery } from "@tanstack/react-query";
import { Cpu, HardDrive, MemoryStick, RefreshCw } from "lucide-react";
import { deploymentApi } from "@/lib/api/contracts/deployment";
import { InlineMessage, Skeleton } from "@/components/layout/Common";
import { UsageRing } from "@/components/charts/UsageRing";

export function SystemResources() {
  const query = useQuery({
    queryKey: ["admin", "system-resources"],
    queryFn: deploymentApi.resources,
    refetchInterval: (query) => query.state.status === "error" ? 10000 : 2000,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    retry: false,
  });
  return <section className="sv-panel overview-panel" aria-labelledby="resources-title">
    <header className="overview-panel-heading">
      <div><h2 id="resources-title">System resources</h2><p>{query.isError ? "Updates delayed · retrying automatically" : "Live host / Docker VM usage · updates every 2 seconds while visible"}</p></div>
      <button className="sv-action-secondary" type="button" disabled={query.isFetching} onClick={() => void query.refetch()}><RefreshCw size={14} aria-hidden="true" /> Refresh</button>
    </header>
    {query.isError ? <InlineMessage tone="warning">Resource refresh failed. {query.data ? "The last sample is shown below." : "Retry to load system usage."}</InlineMessage> : null}
    {query.isLoading ? <Skeleton className="h-40 w-full" /> : null}
    <div className="overview-resources">
      {query.data?.metrics.map((metric) => {
        const Icon = metric.label === "CPU" ? Cpu : metric.label === "Memory" ? MemoryStick : HardDrive;
        const tone = metric.percent !== null && metric.percent >= 90 ? "danger" : metric.percent !== null && metric.percent >= 75 ? "warning" : "accent";
        return <div key={metric.label} className="overview-resource">
          <UsageRing value={metric.percent} label={`${metric.label} usage`} detail="utilized" tone={tone} />
          <div className="overview-resource-copy">
            <h3><Icon size={17} aria-hidden="true" />{metric.label}</h3>
            <p className="overview-resource-capacity">{metric.used_bytes !== null && metric.total_bytes !== null ? `${(metric.used_bytes / 1024 ** 3).toFixed(1)} / ${(metric.total_bytes / 1024 ** 3).toFixed(1)} GiB` : metric.percent === null ? "Unavailable" : "Current utilization"}</p>
            <p className="overview-caption">{metric.unavailable_reason ?? metric.scope}</p>
            {metric.percent !== null && metric.percent >= 75 ? <span className="overview-status" data-tone={tone}>{metric.percent >= 90 ? "High utilization" : "Elevated utilization"}</span> : null}
          </div>
        </div>;
      })}
    </div>
    {query.data ? <section className="overview-gpu" aria-labelledby="gpu-title">
      <h3 id="gpu-title">GPU resources</h3>
      <p className="overview-caption">{query.data.gpu?.scope ?? "GPUs visible to the API container"}</p>
      {query.data.gpu?.devices.length ? query.data.gpu.devices.map((gpu) => <div className="overview-gpu-device" key={gpu.id}>
        <UsageRing value={gpu.utilization_percent} label={`${gpu.name} GPU usage`} detail="GPU utilized" tone="accent" />
        <div className="overview-resource-copy">
          <h3>{gpu.name}</h3>
          <dl className="overview-gpu-stats">
            <div><dt>VRAM</dt><dd>{gpu.memory_used_bytes !== null && gpu.memory_total_bytes !== null ? `${(gpu.memory_used_bytes / 1024 ** 3).toFixed(1)} / ${(gpu.memory_total_bytes / 1024 ** 3).toFixed(1)} GiB` : "Unavailable"}</dd></div>
            <div><dt>Temperature</dt><dd>{gpu.temperature_c === null ? "Unavailable" : `${gpu.temperature_c.toFixed(0)} °C`}</dd></div>
            <div><dt>Power</dt><dd>{gpu.power_watts === null ? "Unavailable" : `${gpu.power_watts.toFixed(1)} W`}</dd></div>
          </dl>
        </div>
      </div>) : <p className="overview-caption"><strong>Unavailable.</strong> {query.data.gpu?.unavailable_reason ?? "GPU telemetry is not available from this runtime."}</p>}
    </section> : null}
    <footer className="overview-panel-footnote">{query.data ? `Sampled ${new Date(query.data.sampled_at).toLocaleTimeString()}. ` : ""}Individual container usage is not collected.</footer>
  </section>;
}
