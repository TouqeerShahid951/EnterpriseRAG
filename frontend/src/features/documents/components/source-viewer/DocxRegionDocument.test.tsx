import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { DocxRegionDocument } from "@/features/documents/components/source-viewer/DocxRegionDocument";

describe("DocxRegionDocument", () => {
  it("renders document search in the normal source toolbar", () => {
    const markup = renderToStaticMarkup(
      <DocxRegionDocument
        buffer={new ArrayBuffer(0)}
        documentId="document-1"
        fallbackMessage="Missing page location"
        regions={[]}
        textTargets={[]}
      />,
    );

    expect(markup).toContain('aria-label="Search document"');
  });

  it("makes extracted image evidence the primary view", () => {
    const markup = renderToStaticMarkup(
      <DocxRegionDocument
        buffer={new ArrayBuffer(0)}
        documentId="document-1"
        fallbackMessage="Missing page location"
        regions={[{
          bbox: null,
          imageAssetId: "asset-1",
          imageSourceKind: "docx_media",
          page: null,
          text: "Visible image text",
        }]}
        textTargets={[]}
      />,
    );

    expect(markup).toContain("source-viewer-image-evidence");
    expect(markup).toContain("Extracted DOCX image");
    expect(markup).toContain("Text search is unavailable for image-only previews");
    expect(markup).toContain("Show in document");
    expect(markup).not.toContain("source-viewer-docx-scroll");
    expect(markup).not.toContain("Zoom out");
  });
});
