import { describe, expect, it } from "vitest";

import type { ColumnSpec } from "../../src/types/ColumnSpec";
import { standingRowsIn } from "../../src/utils/standingRowsIn";
import { aCategoryDetail } from "../support/aCategoryDetail";

const ORDER_COLUMN: ColumnSpec = { key: "no", label: "No.", index: 0, kind: "text", role: "order", choices: [], width: null };
const TITLE_COLUMN: ColumnSpec = { key: "title", label: "Title", index: 1, kind: "text", role: "title", choices: [], width: null };
const NOTE_COLUMN: ColumnSpec = { key: "note", label: "Note", index: 2, kind: "text", role: "other", choices: [], width: null };
const WATCH_COLUMN: ColumnSpec = { key: "seen", label: "Seen", index: 3, kind: "choice", role: "watch", choices: [], width: null };

describe("standingRowsIn", () => {
  it("keys each row by the row number a proposal would name, not by its position in the list", () => {
    const detail = aCategoryDetail({
      rows: [
        { row: 7, cells: { title: "Later" } },
        { row: 2, cells: { title: "Earlier" } },
      ],
    });

    const standing = standingRowsIn(detail);

    expect(standing.cellsByRow[7]).toEqual({ title: "Later" });
    expect(standing.cellsByRow[2]).toEqual({ title: "Earlier" });
    expect(standing.cellsByRow[1]).toBeUndefined();
  });

  it("is ready as soon as the sheet has been read", () => {
    expect(standingRowsIn(aCategoryDetail()).status).toBe("ready");
  });

  it("identifies a row by its title column", () => {
    const detail = aCategoryDetail({ columns: [ORDER_COLUMN, TITLE_COLUMN, NOTE_COLUMN] });

    expect(standingRowsIn(detail).identifyingKey).toBe("title");
  });

  it("falls back to the first column that is neither bookkeeping nor the watch state", () => {
    const detail = aCategoryDetail({ columns: [ORDER_COLUMN, WATCH_COLUMN, NOTE_COLUMN] });

    expect(standingRowsIn(detail).identifyingKey).toBe("note");
  });

  it("has nothing to identify a row with when every column is bookkeeping", () => {
    const detail = aCategoryDetail({ columns: [ORDER_COLUMN, WATCH_COLUMN] });

    expect(standingRowsIn(detail).identifyingKey).toBeNull();
  });
});
