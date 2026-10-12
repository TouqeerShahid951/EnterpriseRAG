import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { JsonRegionDocument } from "./JsonRegionDocument";

describe("JsonRegionDocument", () => {
  it("renders document search in the JSON source toolbar", () => {
    const buffer = new TextEncoder().encode('{"title":"Space Resources"}').buffer as ArrayBuffer;
    const markup = renderToStaticMarkup(
      <JsonRegionDocument buffer={buffer} fallbackMessage="No match" targets={[]} />,
    );

    expect(markup).toContain('aria-label="Search document"');
  });
});
