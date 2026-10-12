import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, expect, it, vi } from "vitest";
import { SystemResources } from "./SystemResources";
import { deploymentApi } from "@/lib/api/contracts/deployment";
import { jsonResponse } from "@/lib/api/contractsTestSupport";

afterEach(() => vi.unstubAllGlobals());

it("renders real zero usage and unavailable counters distinctly", () => {
  const client = new QueryClient();
  client.setQueryData(["admin", "system-resources"], { sampled_at: "2026-09-08T10:00:00Z", metrics: [
    { label: "CPU", scope: "Linux host", percent: 0, used_bytes: null, total_bytes: null, unavailable_reason: null },
    { label: "Memory", scope: "Linux host", percent: null, used_bytes: null, total_bytes: null, unavailable_reason: "OS counters unavailable" },
  ] });
  const html = renderToStaticMarkup(<QueryClientProvider client={client}><SystemResources /></QueryClientProvider>);
  expect(html).toContain("0.0%");
  expect(html).toContain("Unavailable");
  expect(html).toContain("updates every 2 seconds while visible");
  expect(html).toContain('aria-label="CPU usage"');
  expect(html).not.toContain('aria-label="Memory usage"');
});

it("reads the authenticated resource endpoint and propagates errors", async () => {
  const fetchMock = vi.fn(async () => jsonResponse({ sampled_at: "now", metrics: [] }));
  vi.stubGlobal("fetch", fetchMock);
  expect((await deploymentApi.resources()).metrics).toEqual([]);
  const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
  expect(url).toContain("/api/v1/admin/system-resources");
  expect(init.method).toBe("GET");
  fetchMock.mockImplementation(async () => new Response("Forbidden", { status: 403 }));
  await expect(deploymentApi.resources()).rejects.toThrow();
});

it("marks retained samples as delayed after a failed refresh", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const queryKey = ["admin", "system-resources"];
  client.setQueryData(queryKey, { sampled_at: "2026-09-08T10:00:00Z", metrics: [] });
  await client.fetchQuery({ queryKey, queryFn: () => Promise.reject(new Error("Telemetry stale")) }).catch(() => undefined);
  const html = renderToStaticMarkup(<QueryClientProvider client={client}><SystemResources /></QueryClientProvider>);
  expect(html).toContain("Updates delayed");
  expect(html).toContain("The last sample is shown below.");
  expect(html).not.toContain("Live host");
});

it("renders GPU readings without inventing unsupported measurements", () => {
  const client = new QueryClient();
  const snapshot = { sampled_at: "2026-09-08T10:00:00Z", metrics: [], gpu: {
    scope: "Visible GPUs", unavailable_reason: null, devices: [{ id: "GPU-1", name: "NVIDIA RTX", utilization_percent: 0, memory_used_bytes: 1024 ** 3, memory_total_bytes: 8 * 1024 ** 3, temperature_c: null, power_watts: 18.5 }],
  } };
  client.setQueryData(["admin", "system-resources"], snapshot);
  const render = () => renderToStaticMarkup(<QueryClientProvider client={client}><SystemResources /></QueryClientProvider>);
  expect(render()).toContain("NVIDIA RTX");
  expect(render()).toContain("1.0 / 8.0 GiB");
  expect(render()).toContain("18.5 W");
  expect(render()).toContain("0.0%");
  expect(render()).toContain("Unavailable");
  client.setQueryData(["admin", "system-resources"], { ...snapshot, gpu: { devices: [], unavailable_reason: "Mac GPU unavailable" } });
  expect(render()).toContain("Mac GPU unavailable");
  expect(render()).not.toContain("0.0%");
});
