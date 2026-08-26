import { useState, type FormEvent, type ReactElement } from "react";

import { useAppDispatch } from "../hooks/useAppDispatch";
import { addRow } from "../stores/categorySlice";
import type { CategoryDetail } from "../types/CategoryDetail";
import { CellField } from "./CellField";
import { Modal } from "./Modal";

interface AddEntryDialogProps {
  readonly detail: CategoryDetail;
  readonly onClose: () => void;
}

/** Adds a row to the end of the sheet. Order numbering is left to the workbook. */
export function AddEntryDialog({ detail, onClose }: AddEntryDialogProps): ReactElement {
  const dispatch = useAppDispatch();
  const [cells, setCells] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  const editable = detail.columns.filter((column) => column.role !== "order");
  const titleColumn = detail.columns.find((column) => column.role === "title");
  const titleValue = titleColumn === undefined ? "" : (cells[titleColumn.key] ?? "");
  const ready = titleColumn === undefined ? Object.keys(cells).length > 0 : titleValue.trim() !== "";

  const submit = async (event: FormEvent): Promise<void> => {
    event.preventDefault();
    if (!ready || busy) return;
    setBusy(true);
    const result = await dispatch(addRow({ categoryId: detail.id, cells }));
    setBusy(false);
    if (addRow.fulfilled.match(result)) onClose();
  };

  return (
    <Modal title={`Add to ${detail.name}`} onClose={onClose}>
      <form onSubmit={(event) => void submit(event)}>
        <p className="dialog__hint">The entry lands at the end of {detail.sheet_title}.</p>

        {editable.map((column) => (
          <label className="dialog__field" key={column.key}>
            <span className="dialog__label">{column.label}</span>
            <CellField
              column={column}
              value={cells[column.key] ?? ""}
              onCommit={(value) => setCells((current) => ({ ...current, [column.key]: value }))}
            />
          </label>
        ))}

        <div className="dialog__actions">
          <button type="button" className="button" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="button button--primary" disabled={!ready || busy}>
            {busy ? "Adding…" : "Add entry"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
