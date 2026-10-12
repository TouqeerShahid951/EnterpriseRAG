import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import { WorkspaceActivity } from "./WorkspaceActivity";

it("uses aggregate counts rather than the six recent rows and handles empty activity", () => {
  const client = new QueryClient();
  const render = () => renderToStaticMarkup(<QueryClientProvider client={client}><WorkspaceActivity /></QueryClientProvider>);
  client.setQueryData(["audit-log", "overview", 7], { items: [], summary: { total: 120, actor_count: 4, category_counts: { documents: 120 } } });
  expect(render()).toContain("120");
  expect(render()).toContain('aria-label="documents: 120 of 120 events"');
  expect(render()).toContain("distinct actors");
  client.setQueryData(["audit-log", "overview", 7], { items: [], summary: { total: 0, actor_count: 0, category_counts: {} } });
  expect(render()).toContain("No recorded activity in this period.");
});
