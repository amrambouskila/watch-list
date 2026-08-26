import type { ReactElement } from "react";

import type { RowColumns } from "../hooks/useRowColumns";
import type { ColumnSpec } from "../types/ColumnSpec";
import type { WatchRow } from "../types/WatchRow";
import { RowDetail } from "./RowDetail";
import { WatchNode } from "./WatchNode";

interface RouteEntryProps {
  readonly row: WatchRow;
  readonly columns: readonly ColumnSpec[];
  readonly layout: RowColumns;
  readonly watch: ColumnSpec | null;
  readonly status: string;
  readonly reached: boolean;
  readonly expanded: boolean;
  readonly onCycle: (next: string) => void;
  readonly onToggle: () => void;
  readonly onCommit: (columnKey: string, value: string) => void;
  readonly onDelete: () => void;
}

export function RouteEntry({
  row,
  columns,
  layout,
  watch,
  status,
  reached,
  expanded,
  onCycle,
  onToggle,
  onCommit,
  onDelete,
}: RouteEntryProps): ReactElement {
  const title = layout.title === null ? `Row ${row.row}` : (row.cells[layout.title.key] || "Untitled entry");
  const [lead, ...rest] = layout.inline;
  const leadValue = lead === undefined ? "" : (row.cells[lead.key] ?? "");
  const tags = rest
    .map((column) => ({ column, value: row.cells[column.key] ?? "" }))
    .filter((tag) => tag.value !== "");

  return (
    <li className="route__entry" data-reached={reached} data-status={status}>
      <div className="route-row">
        <div className="rail">
          {watch !== null && (
            <WatchNode status={status} choices={watch.choices} title={title} onCycle={onCycle} />
          )}
        </div>
        <div className="route-row__order mono">{layout.order === null ? "" : row.cells[layout.order.key]}</div>
        <div className="route-row__body">
          <span className="route-row__name">{title}</span>
          {leadValue !== "" && <span className="route-row__unit">{leadValue}</span>}
        </div>
        {tags.length > 0 && (
          <div className="route-row__meta">
            {tags.map((tag) => (
              <span className="tag" key={tag.column.key} title={`${tag.column.label}: ${tag.value}`}>
                {tag.value}
              </span>
            ))}
          </div>
        )}
        <button
          type="button"
          className="route-row__expand"
          aria-expanded={expanded}
          aria-label={expanded ? `Hide details for ${title}` : `Edit details for ${title}`}
          onClick={onToggle}
        >
          <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true">
            <polyline
              points="6,3 11,8 6,13"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>
      </div>
      {expanded && <RowDetail columns={columns} row={row} onCommit={onCommit} onDelete={onDelete} />}
    </li>
  );
}
