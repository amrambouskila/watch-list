import { useState, type FormEvent, type ReactElement } from "react";

import { useAppDispatch } from "../hooks/useAppDispatch";
import { retireWorkbook } from "../stores/categorySlice";
import type { CategoryDetail } from "../types/CategoryDetail";
import { Modal } from "./Modal";

/** Where a retirement lands, stated so recovering one by hand is obvious. */
const BACKUPS_FOLDER = "app/.backups";

interface RetireCategoryDialogProps {
  readonly detail: CategoryDetail;
  readonly onClose: () => void;
}

/**
 * The heaviest action in the app, so the button only wakes once the name has been typed out in full.
 *
 * Nothing is deleted: the workbook and its artwork move into the folder the routine snapshots already
 * live in, under one shared timestamp, and moving them back restores the category.
 */
export function RetireCategoryDialog({ detail, onClose }: RetireCategoryDialogProps): ReactElement {
  const dispatch = useAppDispatch();
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const entries = detail.counts.total;
  const confirmed = typed.trim().toLowerCase() === detail.name.toLowerCase();

  const submit = async (event: FormEvent): Promise<void> => {
    event.preventDefault();
    if (!confirmed || busy) return;
    setBusy(true);
    const result = await dispatch(retireWorkbook({ categoryId: detail.id }));
    // A retirement that lands takes this whole stage down with it; there is nothing left to re-render.
    if (retireWorkbook.fulfilled.match(result)) return;
    setBusy(false);
  };

  return (
    <Modal title="Retire this category" onClose={onClose}>
      <form onSubmit={(event) => void submit(event)}>
        <p className="dialog__hint">
          <strong>{detail.name}</strong> and its {entries}{" "}
          {entries === 1 ? "entry" : "entries"} leave the library.{" "}
          <strong>{detail.file_name}</strong> and the card artwork move into{" "}
          <strong className="mono">{BACKUPS_FOLDER}</strong>, beside the routine snapshots, under one
          shared timestamp. Nothing is deleted — moving the workbook back brings the category back.
        </p>

        {detail.locked_by_excel && (
          <p className="dialog__warning">
            {detail.file_name} is open in Excel. Windows will not move a file Excel is holding, so
            close it first.
          </p>
        )}

        <label className="dialog__field">
          <span className="dialog__label">Type {detail.name} to confirm</span>
          <input
            className="field mono"
            value={typed}
            autoFocus
            autoComplete="off"
            spellCheck={false}
            placeholder={detail.name}
            onChange={(event) => setTyped(event.target.value)}
          />
        </label>

        <div className="dialog__actions">
          <button type="button" className="button" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="button button--danger" disabled={!confirmed || busy}>
            {busy ? "Retiring…" : "Retire category"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
