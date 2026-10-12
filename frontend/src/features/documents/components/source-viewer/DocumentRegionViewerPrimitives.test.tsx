import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { ImageAssetStrip } from "./DocumentRegionViewerPrimitives";

describe("ImageAssetStrip", () => {
  it("makes image evidence a keyboard-accessible shortcut to its own or cited page", () => {
    const markup = renderToStaticMarkup(
      <ImageAssetStrip
        documentId="document-1"
        fallbackPage={8}
        onOpenPage={vi.fn()}
        regions={[{ bbox: null, imageAssetId: "asset-1", imageSourceKind: "pdf_image", page: null, text: "Device photo" }]}
      />,
    );

    expect(markup).toContain('aria-label="Open image on page 8"');
    expect(markup).toContain('<button');
  });
});
