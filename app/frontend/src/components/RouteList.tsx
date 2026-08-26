import { useMemo, type ReactElement } from "react";

import { useAppDispatch } from "../hooks/useAppDispatch";
import { useRowColumns } from "../hooks/useRowColumns";
import { removeRow, writeRow } from "../stores/categorySlice";
import { toggleRow } from "../stores/uiSlice";
import type { CategoryDetail } from "../types/CategoryDetail";
import type { ColumnSpec } from "../types/ColumnSpec";
import type { WatchRow } from "../types/WatchRow";
import { WATCHED } from "../types/WatchStatus";
import { RouteEntry } from "./RouteEntry";

interface RouteListProps {
  readonly detail: CategoryDetail;
  readonly watch: ColumnSpec | null;
  readonly rows: readonly WatchRow[];
  readonly expandedRow: number | null;
}

export function RouteList({ detail, watch, rows, expandedRow }: RouteListProps): ReactElement {
  const dispatch = useAppDispatch();
  const layout = useRowColumns(detail.columns);

  /** Everything up to and including the last watched entry counts as ground covered. */
  const reached = useMemo(() => {
    if (watch === null) return new Set<number>();
    let frontier = -1;
    detail.rows.forEach((row, index) => {
      if (row.cells[watch.key] === WATCHED) frontier = index;
    });
    return new Set(detail.rows.slice(0, frontier + 1).map((row) => row.row));
  }, [detail.rows, watch]);

  const commit = (row: WatchRow, columnKey: string, value: string): void => {
    dispatch(
      writeRow({
        categoryId: detail.id,
        row: row.row,
        cells: { [columnKey]: value },
        previous: { [columnKey]: row.cells[columnKey] ?? "" },
      }),
    );
  };

  const remove = (row: WatchRow, title: string): void => {
    if (!window.confirm(`Delete "${title}" from ${detail.name}? This rewrites the workbook.`)) return;
    dispatch(removeRow({ categoryId: detail.id, row: row.row }));
  };

  return (
    <ol className="route">
      {rows.map((row) => {
        const status = watch === null ? "" : (row.cells[watch.key] ?? "");
        const title = layout.title === null ? `Row ${row.row}` : (row.cells[layout.title.key] || "Untitled entry");
        return (
          <RouteEntry
            key={row.row}
            row={row}
            columns={detail.columns}
            layout={layout}
            watch={watch}
            status={status}
            reached={reached.has(row.row)}
            expanded={expandedRow === row.row}
            onCycle={(next) => watch !== null && commit(row, watch.key, next)}
            onToggle={() => dispatch(toggleRow(row.row))}
            onCommit={(columnKey, value) => commit(row, columnKey, value)}
            onDelete={() => remove(row, title)}
          />
        );
      })}
    </ol>
  );
}
