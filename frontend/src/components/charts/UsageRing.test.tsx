import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import { UsageRing } from "./UsageRing";

it("clamps percentages and distinguishes unavailable data from zero", () => {
  const render = (value: number | null) => renderToStaticMarkup(<UsageRing value={value} label="CPU usage" detail="utilized" />);
  expect(render(0)).toContain('aria-valuenow="0"');
  expect(render(100)).toContain('stroke-dasharray="100 100"');
  expect(render(125)).toContain('aria-valuenow="100"');
  expect(render(-5)).toContain('aria-valuenow="0"');
  expect(render(null)).toContain("Unavailable");
  expect(render(null)).not.toContain('role="meter"');
});
