import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ImageRegionDocument } from "./ImageRegionDocument";

describe("ImageRegionDocument", () => {
  it("explains that bitmap-only previews cannot search text", () => {
    const markup = renderToStaticMarkup(
      <ImageRegionDocument
        buffer={new ArrayBuffer(0)}
        contentType="image/png"
        fallbackMessage="No highlight"
        regions={[]}
      />,
    );

    expect(markup).toContain("Text search is unavailable for image-only previews");
  });
});
