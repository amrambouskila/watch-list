import { useEffect, useState, type ReactElement } from "react";

import type { ColumnSpec } from "../types/ColumnSpec";
import { statusLabel } from "../utils/statusLabel";

interface CellFieldProps {
  readonly column: ColumnSpec;
  readonly value: string;
  readonly onCommit: (value: string) => void;
  readonly autoFocus?: boolean;
}

const LONG_TEXT_WIDTH = 45;

/**
 * One editable cell. Columns the sheet already constrains with a dropdown stay
 * constrained here, so the app can never write a value Excel would reject.
 */
export function CellField({ column, value, onCommit, autoFocus = false }: CellFieldProps): ReactElement {
  const [draft, setDraft] = useState(value);

  useEffect(() => setDraft(value), [value]);

  if (column.kind === "choice") {
    return (
      <select
        className="cell-input"
        value={value}
        onChange={(event) => onCommit(event.target.value)}
        aria-label={column.label}
      >
        {column.choices.map((choice) => (
          <option key={choice || "blank"} value={choice}>
            {column.role === "watch" ? statusLabel(choice) : choice || "—"}
          </option>
        ))}
      </select>
    );
  }

  const commit = (): void => {
    if (draft !== value) onCommit(draft);
  };

  if (column.role === "other" && (column.width ?? 0) >= LONG_TEXT_WIDTH) {
    return (
      <textarea
        className="cell-input"
        rows={3}
        value={draft}
        autoFocus={autoFocus}
        aria-label={column.label}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
      />
    );
  }

  return (
    <input
      className="cell-input"
      type="text"
      value={draft}
      autoFocus={autoFocus}
      aria-label={column.label}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === "Enter") event.currentTarget.blur();
        if (event.key === "Escape") setDraft(value);
      }}
    />
  );
}
