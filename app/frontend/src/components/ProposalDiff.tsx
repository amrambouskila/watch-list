import type { ReactElement } from "react";

import type { ProposalCreate } from "../types/ProposalCreate";
import type { ProposalEdit } from "../types/ProposalEdit";
import type { RowChange, RowChangeKind } from "../types/RowChange";
import type { StandingRows } from "../types/StandingRows";
import { anchorOf } from "../utils/anchorOf";
import { identifyRow } from "../utils/identifyRow";
import { ProposalRow } from "./ProposalRow";

const STANDING_HEADER = "Now";
// A row these change kinds name is one the sheet already holds, so without its own text the user
// would be approving a deletion, a reordering or an overwrite identified by row number alone.
const NAMED_BY_THE_SHEET: readonly RowChangeKind[] = ["remove", "move", "revise"];

interface DiffLine {
  kind: RowChangeKind;
  anchor: string;
  cells: Record<string, string>;
  standing: string;
  /** What the sheet holds in the very cells this line would rewrite; empty unless it rewrites any. */
  overwrites: Record<string, string>;
  reason: string;
}

interface ProposalDiffProps {
  readonly body: ProposalCreate | ProposalEdit;
  readonly standing: StandingRows;
}

/** Which row of the sheet a change names, or nothing when it names none. */
function targetRow(change: RowChange): number | null {
  return NAMED_BY_THE_SHEET.includes(change.kind) && change.row !== undefined ? change.row : null;
}

/** What identifies the row a change names today, or a plain word about why that is not known. */
function standingAt(standing: StandingRows, change: RowChange): string {
  const row = targetRow(change);
  return row === null ? "" : identifyRow(standing, row);
}

/**
 * The text a revise would replace, cell by cell.
 *
 * Without it a revise that blanks a cell renders as an empty box, indistinguishable from a line
 * that changes nothing, while the write erases whatever the owner had put there.
 */
function overwrittenBy(standing: StandingRows, change: RowChange): Record<string, string> {
  const row = targetRow(change);
  if (change.kind !== "revise" || row === null || standing.status !== "ready") return {};
  const cells = standing.cellsByRow[row];
  if (cells === undefined) return {};
  return Object.fromEntries(Object.keys(change.cells).map((key) => [key, cells[key] ?? ""]));
}

/** A new sheet is a list of additions; an edit is its own list of changes. Both render the same. */
function linesOf(body: ProposalCreate | ProposalEdit, standing: StandingRows): DiffLine[] {
  if (body.kind === "create") {
    return body.category.rows.map((cells, index) => ({
      kind: "add",
      anchor: String(index + 1),
      cells,
      standing: "",
      overwrites: {},
      reason: "",
    }));
  }
  return body.changes.map((change) => ({
    kind: change.kind,
    anchor: anchorOf(change, standing),
    cells: change.cells,
    standing: standingAt(standing, change),
    overwrites: overwrittenBy(standing, change),
    reason: change.reason,
  }));
}

/** The column keys the changes actually touch, in the order they first appear. */
function columnKeysOf(lines: readonly DiffLine[]): string[] {
  const keys: string[] = [];
  for (const line of lines) {
    for (const key of Object.keys(line.cells)) if (!keys.includes(key)) keys.push(key);
  }
  return keys;
}

export function ProposalDiff({ body, standing }: ProposalDiffProps): ReactElement {
  const lines = linesOf(body, standing);
  const columnKeys = columnKeysOf(lines);
  const naming = lines.some((line) => line.standing !== "");

  return (
    <div className="diff scroll" tabIndex={0} role="group" aria-label="Proposed rows">
      <table className="diff__table">
        <thead>
          <tr>
            <th scope="col">Change</th>
            <th scope="col">Row</th>
            {naming && <th scope="col">{STANDING_HEADER}</th>}
            {columnKeys.map((key) => (
              <th scope="col" key={key}>
                {key}
              </th>
            ))}
            <th scope="col">Why</th>
          </tr>
        </thead>
        <tbody>
          {lines.map((line, index) => (
            <ProposalRow
              key={index}
              kind={line.kind}
              anchor={line.anchor}
              standing={naming ? line.standing : null}
              cells={line.cells}
              overwrites={line.overwrites}
              reason={line.reason}
              columnKeys={columnKeys}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}
