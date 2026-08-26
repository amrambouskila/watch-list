import type { ReactElement } from "react";

import type { RowChangeKind } from "../types/RowChange";

const KIND_LABELS: Readonly<Record<RowChangeKind, string>> = {
  add: "Add",
  revise: "Revise",
  move: "Move",
  remove: "Remove",
};
const REPLACES = " → ";
const ERASED = "(blank)";

interface ProposalRowProps {
  readonly kind: RowChangeKind;
  /** Where the change lands: an ordinal for a new sheet, a row reference for an edit. */
  readonly anchor: string;
  /** What the sheet holds at that row today, or null when this diff shows no such column. */
  readonly standing: string | null;
  readonly cells: Record<string, string>;
  /** What this line would replace, per column key; empty when it replaces nothing. */
  readonly overwrites: Record<string, string>;
  readonly reason: string;
  readonly columnKeys: readonly string[];
}

/** An erased cell has to read as an erasure, not as an empty box that might mean nothing happens. */
function legible(value: string): string {
  return value === "" ? ERASED : value;
}

export function ProposalRow({
  kind,
  anchor,
  standing,
  cells,
  overwrites,
  reason,
  columnKeys,
}: ProposalRowProps): ReactElement {
  return (
    <tr className={`diff__row diff__row--${kind}`}>
      <td>
        <span className={`diff__badge diff__badge--${kind}`}>{KIND_LABELS[kind]}</span>
      </td>
      <td className="mono diff__anchor">{anchor}</td>
      {standing !== null && (
        <td className="diff__standing" title={standing}>
          {standing}
        </td>
      )}
      {columnKeys.map((key) => {
        // A column this line does not write is the one case that may render as an empty box; every
        // cell it does write is spelled out, so an erasure can never pass for a line doing nothing.
        if (!Object.hasOwn(cells, key)) return <td key={key} />;
        const value = cells[key] ?? "";
        const replaced = overwrites[key];
        if (replaced === value) {
          return (
            <td key={key} title={value}>
              {value}
            </td>
          );
        }
        if (replaced === undefined) {
          return (
            <td key={key} title={legible(value)}>
              {legible(value)}
            </td>
          );
        }
        return (
          <td key={key} title={`${legible(replaced)}${REPLACES}${legible(value)}`}>
            <span className="diff__replaced">{legible(replaced)}</span>
            {REPLACES}
            {legible(value)}
          </td>
        );
      })}
      <td className="diff__reason">{reason}</td>
    </tr>
  );
}
