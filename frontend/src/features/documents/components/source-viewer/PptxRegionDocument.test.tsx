import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({ values: [] as unknown[] }));
vi.mock("react", async (importOriginal) => ({
  ...await importOriginal<typeof import("react")>(),
  useState: () => [state.values.shift(), vi.fn()],
}));
vi.mock("./ImageRegionDocument", () => ({
  ImageRegionDocument: ({ fallbackMessage, regions }: { fallbackMessage: string; regions: unknown[] }) => (
    <div>Image: {regions.length} highlights. {fallbackMessage}</div>
  ),
}));
import { PptxRegionDocument } from "./PptxRegionDocument";

beforeEach(() => { state.values = []; });

it("keeps highlights on their slide and offers a return to cited evidence", () => {
  const render = (page: number, citedPage: number | null) => {
    state.values = [page, [1, 2, 3], null, 0, 0,
      { key: JSON.stringify(["demo", page, undefined, 0]), buffer: new ArrayBuffer(0), contentType: "image/png" }, null];
    return renderToStaticMarkup(<PptxRegionDocument documentId="demo" initialPage={2} citedPage={citedPage}
      fallbackMessage="Highlight unavailable" regions={[{ page: 2, bbox: [0, 0, 10, 10], text: "Evidence" }]} />);
  };
  const adjacent = render(3, 2);
  expect(adjacent).toContain("Return to cited slide");
  expect(adjacent).toContain("3 of 3");
  expect(adjacent).toContain("Image: 0 highlights.");
  expect(adjacent).not.toContain("Highlight unavailable");
  expect(render(2, 2)).toContain("Image: 1 highlights.");
  const document = render(1, null);
  expect(document).not.toContain("Return to cited slide");
  expect(document).not.toContain("Highlight unavailable");
});

it("offers retry and reingestion guidance when no rendered slides exist", () => {
  state.values = [2, [], null, 0, 0, null, null];
  const markup = renderToStaticMarkup(<PptxRegionDocument documentId="demo" initialPage={2}
    fallbackMessage="Highlight unavailable" regions={[]} />);
  expect(markup).toContain("No slide previews are available yet.");
  expect(markup).toContain("Retry preview");
  expect(markup).toContain("reingest the presentation");
  expect(markup).not.toContain("Opening original source");
});
