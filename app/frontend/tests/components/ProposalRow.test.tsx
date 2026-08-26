import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ProposalRow } from "../../src/components/ProposalRow";
import type { RowChangeKind } from "../../src/types/RowChange";

const COLUMNS = ["title", "note"];

interface RowDraft {
  readonly kind?: RowChangeKind;
  readonly anchor?: string;
  readonly standing?: string | null;
  readonly cells?: Record<string, string>;
  readonly overwrites?: Record<string, string>;
  readonly reason?: string;
}

function renderRow(draft: RowDraft = {}): void {
  render(
    <table>
      <tbody>
        <ProposalRow
          kind={draft.kind ?? "revise"}
          anchor={draft.anchor ?? "4"}
          standing={draft.standing === undefined ? null : draft.standing}
          cells={draft.cells ?? {}}
          overwrites={draft.overwrites ?? {}}
          reason={draft.reason ?? ""}
          columnKeys={COLUMNS}
        />
      </tbody>
    </table>,
  );
}

function cells(): string[] {
  return within(screen.getByRole("row"))
    .getAllByRole("cell")
    .map((cell) => cell.textContent ?? "");
}

describe("ProposalRow", () => {
  it.each([
    ["add", "Add"],
    ["revise", "Revise"],
    ["move", "Move"],
    ["remove", "Remove"],
  ] as const)("labels a %s with the word %s", (kind, label) => {
    renderRow({ kind });

    expect(cells()[0]).toBe(label);
  });

  it("shows where the change lands and why", () => {
    renderRow({ anchor: "3 → to the top", reason: "release order" });

    expect(cells()[1]).toBe("3 → to the top");
    expect(cells().at(-1)).toBe("release order");
  });

  it("leaves out the standing column entirely when the diff shows none", () => {
    renderRow({ cells: { title: "New" } });

    expect(cells()).toEqual(["Revise", "4", "New", "", ""]);
  });

  it("gives the standing text its own cell when the diff shows one", () => {
    renderRow({ standing: "The Standing Row", cells: { title: "New" } });

    expect(cells()).toEqual(["Revise", "4", "The Standing Row", "New", "", ""]);
  });

  it("shows what a cell would replace, so the write is never understated", () => {
    renderRow({ cells: { note: "corrected" }, overwrites: { note: "the owner's note" } });

    expect(cells()[3]).toBe("the owner's note → corrected");
  });

  it("names an erasure rather than rendering it as an empty box", () => {
    renderRow({ cells: { note: "" }, overwrites: { note: "the owner's note" } });

    expect(cells()[3]).toBe("the owner's note → (blank)");
  });

  it("names an empty cell being filled, so the arrow is never one-sided", () => {
    renderRow({ cells: { note: "added" }, overwrites: { note: "" } });

    expect(cells()[3]).toBe("(blank) → added");
  });

  it("names an erasure even when what it replaces is unknown, so an unread sheet hides nothing", () => {
    renderRow({ cells: { note: "" } });

    expect(cells()[3]).toBe("(blank)");
  });

  it("says nothing about a replacement when the value is not changing", () => {
    renderRow({ cells: { note: "unchanged" }, overwrites: { note: "unchanged" } });

    expect(cells()[3]).toBe("unchanged");
  });

  it("carries the whole replacement in the cell's tooltip, since the column can be too narrow to read", () => {
    renderRow({ cells: { note: "" }, overwrites: { note: "the owner's note" } });

    const noteCell = within(screen.getByRole("row")).getAllByRole("cell")[3];

    expect(noteCell).toHaveAttribute("title", "the owner's note → (blank)");
  });

  it("leaves a column this change does not write empty rather than blanking it", () => {
    renderRow({ cells: { note: "only the note" } });

    expect(cells()[2]).toBe("");
  });
});
