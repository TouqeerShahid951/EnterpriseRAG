import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { GeneratedArtifact } from "../../types/api";
import { ArtifactDownloads } from "./AssistantZipTurn";

const artifact: GeneratedArtifact = {
  id: "artifact-1",
  filename: "records-retention.pdf",
  format: "pdf",
  content_type: "application/pdf",
  size_bytes: 1536,
  download_url: "/api/v1/query/artifacts/artifact-1/content",
  created_at: "2026-06-12T00:00:00+00:00",
};

describe("ArtifactDownloads", () => {
  it("renders generated artifact download links", () => {
    const markup = renderToStaticMarkup(<ArtifactDownloads artifacts={[artifact]} />);

    expect(markup).toContain("records-retention.pdf");
    expect(markup).toContain("PDF");
    expect(markup).toContain("2 KB");
    expect(markup).toContain('download="records-retention.pdf"');
    expect(markup).toContain("http://localhost:8000/api/v1/query/artifacts/artifact-1/content");
  });
});
