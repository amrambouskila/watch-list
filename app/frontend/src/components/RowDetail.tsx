import type { ReactElement } from "react";

import type { ColumnSpec } from "../types/ColumnSpec";
import type { WatchRow } from "../types/WatchRow";
import { CellField } from "./CellField";

interface RowDetailProps {
  readonly columns: readonly ColumnSpec[];
  readonly row: WatchRow;
  readonly onCommit: (columnKey: string, value: string) => void;
  readonly onDelete: () => void;
}

/** Every column of one entry, editable. Order is left to the sheet to keep contiguous. */
export function RowDetail({ columns, row, onCommit, onDelete }: RowDetailProps): ReactElement {
  return (
    <div className="detail">
      {columns
        .filter((column) => column.role !== "order")
        .map((column) => (
          <label className="detail__field" key={column.key}>
            <span className="detail__label">{column.label}</span>
            <CellField
              column={column}
              value={row.cells[column.key] ?? ""}
              onCommit={(value) => onCommit(column.key, value)}
            />
          </label>
        ))}
      <div className="detail__footer">
        <button type="button" className="button button--danger" onClick={onDelete}>
          Delete entry
        </button>
      </div>
    </div>
  );
}
