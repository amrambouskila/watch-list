import { describe, expect, it } from "vitest";

import { entryForRow } from "../../src/utils/entryForRow";
import { aCategoryDetail } from "../support/aCategoryDetail";
import { aCuratedEntryRead } from "../support/aCuratedEntryRead";

const ROW = { row: 2, cells: { no: "1", title: "A Film", watched: "" } };
const DETAIL = aCategoryDetail({ rows: [ROW] });
const ENTRY = aCuratedEntryRead({ categorySlug: DETAIL.id, cells: ROW.cells });

describe("entryForRow", () => {
  it("joins on sheet row, not list position, while ignoring the lossy watch mirror", () => {
    const entry = { ...ENTRY, position: 90, cells: { ...ENTRY.cells, watched: "Watched" } };
    expect(entryForRow([entry], DETAIL, ROW)).toBe(entry);
  });

  it.each([
    { ...ENTRY, category_slug: "another-category" },
    { ...ENTRY, sheet_row: null },
    { ...ENTRY, sheet_row: 3 },
    { ...ENTRY, cells: { ...ENTRY.cells, title: "A Different Film" } },
  ])("refuses a stale or unrelated projection %#", (entry) => {
    expect(entryForRow([entry], DETAIL, ROW)).toBeNull();
  });

  it("refuses duplicate row claims and absent projections", () => {
    expect(entryForRow([ENTRY, { ...ENTRY, id: "another" }], DETAIL, ROW)).toBeNull();
    expect(entryForRow([], DETAIL, ROW)).toBeNull();
  });

  it("treats omitted blank cells the same as the workbook's empty strings", () => {
    const empty = { row: 2, cells: {} };
    const entry = { ...ENTRY, cells: {} };
    expect(entryForRow([entry], DETAIL, empty)).toBe(entry);
  });
});
