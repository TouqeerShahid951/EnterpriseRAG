import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { PdfRegionDocument } from "./PdfRegionDocument";

describe("PdfRegionDocument", () => {
  it("renders document search in the PDF toolbar", () => {
    const markup = renderToStaticMarkup(
      <PdfRegionDocument
        buffer={new ArrayBuffer(0)}
        documentId="document-1"
        fallbackMessage="No highlight"
        initialPage={1}
        regions={[]}
      />,
    );

    expect(markup).toContain('type="search"');
    expect(markup).toContain('aria-label="Search document"');
    expect(markup).toContain('class="source-viewer-pdf-text-layer textLayer"');
  });
});
