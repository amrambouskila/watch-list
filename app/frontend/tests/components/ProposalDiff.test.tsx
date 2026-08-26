import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ProposalDiff } from "../../src/components/ProposalDiff";
import type { ProposalCreate } from "../../src/types/ProposalCreate";
import type { ProposalEdit } from "../../src/types/ProposalEdit";
import type { StandingRows } from "../../src/types/StandingRows";
import { aCreateBody, anEditBody } from "../support/aProposalBody";
import { aRowChange } from "../support/aRowChange";
import { aReadSheet, aSheetBeingRead, anUnreadableSheet } from "../support/aStandingSheet";

const STANDING = aReadSheet("title", {
  2: { title: "The Second Row", note: "the owner's note" },
  4: { title: "The Fourth Row", note: "" },
});

function show(body: ProposalCreate | ProposalEdit, standing: StandingRows = STANDING): void {
  render(<ProposalDiff body={body} standing={standing} />);
}

function headers(): string[] {
  return screen.getAllByRole("columnheader").map((header) => header.textContent ?? "");
}

function bodyRows(): HTMLElement[] {
  return screen.getAllByRole("row").slice(1);
}

function cellsOf(index: number): string[] {
  const row = bodyRows()[index];
  if (row === undefined) throw new Error(`the diff rendered no row ${index}`);
  return within(row)
    .getAllByRole("cell")
    .map((cell) => cell.textContent ?? "");
}

describe("ProposalDiff", () => {
  it("shows what a revise would replace, cell by cell, so an erasure cannot pass as a no-op", () => {
    show(anEditBody([aRowChange({ kind: "revise", row: 2, cells: { note: "" }, reason: "duplicated" })]));

    expect(headers()).toEqual(["Change", "Row", "Now", "note", "Why"]);
    expect(cellsOf(0)).toEqual(["Revise", "2", "The Second Row", "the owner's note → (blank)", "duplicated"]);
  });

  it("shows a revise of a cell the sheet holds nothing in as a fill, not as an unexplained value", () => {
    show(anEditBody([aRowChange({ kind: "revise", row: 4, cells: { note: "added" } })]));

    expect(cellsOf(0)[3]).toBe("(blank) → added");
  });

  it("does not pretend a revise changes a cell it leaves as it stands", () => {
    show(anEditBody([aRowChange({ kind: "revise", row: 2, cells: { note: "the owner's note" } })]));

    expect(cellsOf(0)[3]).toBe("the owner's note");
  });

  it("names the standing row a removal would take out", () => {
    show(anEditBody([aRowChange({ kind: "remove", row: 2, reason: "watched twice" })]));

    expect(cellsOf(0)).toEqual(["Remove", "2", "The Second Row", "watched twice"]);
  });

  it("names both the row a move takes and the row it would sit behind", () => {
    show(anEditBody([aRowChange({ kind: "move", row: 4, after_row: 2 })]));

    expect(cellsOf(0)[1]).toBe("4 → after 2 · The Second Row");
    expect(cellsOf(0)[2]).toBe("The Fourth Row");
  });

  it.each([
    ["the sheet has been read", STANDING, "The Second Row"],
    ["the sheet is still being read", aSheetBeingRead(), "reading the sheet…"],
    ["the sheet could not be read", anUnreadableSheet(), "could not read the sheet"],
    ["the row is no longer in the sheet", aReadSheet("title", {}), "no such row now"],
  ])("says what stands at the target row when %s", (_case, standing, expected) => {
    show(anEditBody([aRowChange({ kind: "revise", row: 2, cells: { note: "corrected" } })]), standing);

    expect(cellsOf(0)[2]).toBe(expected);
  });

  it.each([
    ["is still being read", aSheetBeingRead()],
    ["could not be read", anUnreadableSheet()],
    ["no longer holds the row", aReadSheet("title", {})],
  ])("still reads an erasure as an erasure when the sheet %s", (_case, standing) => {
    show(anEditBody([aRowChange({ kind: "revise", row: 2, cells: { note: "" } })]), standing);

    expect(cellsOf(0)[3]).toBe("(blank)");
  });

  it("claims no knowledge of what it would overwrite until the sheet has actually been read", () => {
    show(anEditBody([aRowChange({ kind: "revise", row: 2, cells: { note: "corrected" } })]), aSheetBeingRead());

    expect(cellsOf(0)[3]).toBe("corrected");
  });

  it("claims no knowledge of what it would overwrite when the row has gone", () => {
    show(anEditBody([aRowChange({ kind: "revise", row: 2, cells: { note: "corrected" } })]), aReadSheet("title", {}));

    expect(cellsOf(0)[3]).toBe("corrected");
  });

  it("numbers the rows of a new category from one and calls each an addition", () => {
    show(aCreateBody([{ Title: "First" }, { Title: "Second" }]));

    expect(bodyRows()).toHaveLength(2);
    expect(cellsOf(0)).toEqual(["Add", "1", "First", ""]);
    expect(cellsOf(1)).toEqual(["Add", "2", "Second", ""]);
  });

  it("leaves out the standing column when nothing in the proposal touches a row the sheet holds", () => {
    show(aCreateBody([{ Title: "First" }]));

    expect(headers()).toEqual(["Change", "Row", "Title", "Why"]);
  });

  it("leaves out the standing column for an edit that only adds rows", () => {
    show(anEditBody([aRowChange({ kind: "add", after_row: 2, cells: { title: "New" } })]));

    expect(headers()).toEqual(["Change", "Row", "title", "Why"]);
    expect(cellsOf(0)[1]).toBe("after 2");
  });

  it("leaves an addition's standing cell empty, since an addition overwrites nothing", () => {
    show(
      anEditBody([
        aRowChange({ kind: "add", cells: { title: "New" } }),
        aRowChange({ kind: "remove", row: 2 }),
      ]),
    );

    expect(cellsOf(0)).toEqual(["Add", "at the end", "", "New", ""]);
    expect(cellsOf(1)[2]).toBe("The Second Row");
  });

  it("shows every column the proposal writes, in the order the changes first name them", () => {
    show(
      anEditBody([
        aRowChange({ kind: "revise", row: 2, cells: { note: "corrected" } }),
        aRowChange({ kind: "revise", row: 4, cells: { title: "Renamed", note: "also" } }),
      ]),
    );

    expect(headers()).toEqual(["Change", "Row", "Now", "note", "title", "Why"]);
  });

  it("leaves a column a change does not write empty rather than showing it as blanked", () => {
    show(
      anEditBody([
        aRowChange({ kind: "revise", row: 2, cells: { note: "corrected" } }),
        aRowChange({ kind: "revise", row: 4, cells: { title: "Renamed" } }),
      ]),
    );

    expect(cellsOf(0)[4]).toBe("");
    expect(cellsOf(1)[3]).toBe("");
  });

  it("shows no values for a move, because a move rewrites no cell", () => {
    show(
      anEditBody([
        aRowChange({ kind: "revise", row: 2, cells: { note: "corrected" } }),
        aRowChange({ kind: "move", row: 4, after_row: 2 }),
      ]),
    );

    expect(headers()).toEqual(["Change", "Row", "Now", "note", "Why"]);
    expect(cellsOf(1)).toEqual(["Move", "4 → after 2 · The Second Row", "The Fourth Row", "", ""]);
  });

  it("renders one line per change, in the order the proposal lists them", () => {
    show(
      anEditBody([
        aRowChange({ kind: "remove", row: 4 }),
        aRowChange({ kind: "revise", row: 2, cells: { note: "corrected" } }),
        aRowChange({ kind: "move", row: 2, after_row: 1 }),
      ]),
    );

    expect(bodyRows().map((row) => within(row).getAllByRole("cell")[0]?.textContent)).toEqual([
      "Remove",
      "Revise",
      "Move",
    ]);
  });

  it("scrolls the wide table inside itself so the page never has to scroll sideways", () => {
    show(anEditBody([aRowChange({ kind: "revise", row: 2, cells: { note: "corrected" } })]));

    expect(screen.getByRole("group", { name: "Proposed rows" })).toHaveClass("scroll");
  });
});
