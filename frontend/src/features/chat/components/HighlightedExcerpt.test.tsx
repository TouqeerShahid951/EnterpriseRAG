import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import { HighlightedExcerpt } from "./HighlightedExcerpt";

it("converts source code points to UTF-16 after non-BMP characters", () => {
  const markup = renderToStaticMarkup(<HighlightedExcerpt excerpt="😀 اردو متن" ranges={[{ start: 2, end: 10 }]} />);
  expect(markup).toContain('>اردو متن</mark>');
  expect(markup).toContain('😀 ');
});

it("rejects malformed source ranges", () => {
  const markup = renderToStaticMarkup(<HighlightedExcerpt excerpt="😀 Text" ranges={[{ start: -1, end: 2 }, { start: 2, end: 99 }]} />);
  expect(markup).not.toContain('<mark');
});
