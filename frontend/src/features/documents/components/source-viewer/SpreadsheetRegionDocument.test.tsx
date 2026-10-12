import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import * as XLSX from "@e965/xlsx";

import { findSpreadsheetMatches, SpreadsheetRegionDocument } from "./SpreadsheetRegionDocument";

describe("SpreadsheetRegionDocument", () => {
  it("finds matching cells across workbook sheets", () => {
    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, XLSX.utils.aoa_to_sheet([["Name"], ["Ada"]]), "People");
    XLSX.utils.book_append_sheet(workbook, XLSX.utils.aoa_to_sheet([["Title"], ["Space Resources"]]), "Topics");

    expect(findSpreadsheetMatches(workbook, "space resources")).toEqual([{ sheetName: "Topics", row: 1, column: 0 }]);
  });

  it("renders CSV cells and marks cited evidence", () => {
    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, XLSX.utils.aoa_to_sheet([["Name", "Role"], ["Ada", "Analyst"]]), "People");
    const buffer = XLSX.write(workbook, { bookType: "csv", type: "array" });

    const markup = renderToStaticMarkup(
      <SpreadsheetRegionDocument
        buffer={buffer}
        documentTitle="people.csv"
        fallbackMessage="No match"
        targets={[{
          kind: "spreadsheet",
          sheet_name: "People",
          start_row: 1,
          end_row: 2,
          start_column: 0,
          end_column: 1,
          exact_text: "Ada",
        }]}
      />,
    );

    expect(markup).toContain("CSV source");
    expect(markup).toContain("Ada");
    expect(markup).toContain('class="is-cited"');
  });
});
