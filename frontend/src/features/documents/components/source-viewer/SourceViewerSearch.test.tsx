import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { SourceViewerSearch } from "./SourceViewerSearch";

describe("SourceViewerSearch", () => {
  it("renders an accessible search field and result navigation", () => {
    const markup = renderToStaticMarkup(
      <SourceViewerSearch
        query="space"
        resultLabel="1 of 2"
        status="Found on page 2"
        onNext={() => undefined}
        onPrevious={() => undefined}
        onQueryChange={() => undefined}
        onSearch={() => undefined}
      />,
    );

    expect(markup).toContain('role="search"');
    expect(markup).toContain('type="search"');
    expect(markup).toContain('aria-label="Search document"');
    expect(markup).toContain("1 of 2");
  });
});
