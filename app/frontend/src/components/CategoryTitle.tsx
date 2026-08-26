import { useEffect, useRef, useState, type FormEvent, type ReactElement } from "react";

import { useAppDispatch } from "../hooks/useAppDispatch";
import { renameWorkbook } from "../stores/categorySlice";
import { loadCatalog } from "../stores/catalogSlice";
import type { CategoryDetail } from "../types/CategoryDetail";

const WORKBOOK_SUFFIX = ".xlsx";

interface CategoryTitleProps {
  readonly detail: CategoryDetail;
}

/**
 * The category name IS the workbook's filename stem, so renaming edits the filename directly and
 * previews the file it will land as.
 */
export function CategoryTitle({ detail }: CategoryTitleProps): ReactElement {
  const dispatch = useAppDispatch();
  const stem = detail.file_name.replace(/\.xlsx$/i, "");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(stem);
  const [busy, setBusy] = useState(false);
  const field = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    setDraft(stem);
    setEditing(false);
  }, [stem]);

  useEffect(() => {
    if (editing) field.current?.select();
  }, [editing]);

  const cancel = (): void => {
    setDraft(stem);
    setEditing(false);
  };

  const submit = async (event: FormEvent): Promise<void> => {
    event.preventDefault();
    const wanted = draft.trim();
    if (busy || wanted === "" || wanted === stem) {
      cancel();
      return;
    }
    setBusy(true);
    const result = await dispatch(renameWorkbook({ categoryId: detail.id, stem: wanted }));
    setBusy(false);
    if (renameWorkbook.fulfilled.match(result)) {
      setEditing(false);
      void dispatch(loadCatalog());
    }
  };

  if (!editing) {
    return (
      <h1 className="banner__title">
        <button type="button" className="banner__rename" onClick={() => setEditing(true)} title={detail.file_name}>
          {detail.name}
          <svg className="banner__pencil" viewBox="0 0 16 16" aria-hidden="true">
            <path
              d="M11.5 1.8l2.7 2.7L5.6 13.1 2 14l.9-3.6z"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.4"
              strokeLinejoin="round"
            />
          </svg>
          <span className="visually-hidden">Rename category</span>
        </button>
      </h1>
    );
  }

  return (
    <form className="rename" onSubmit={(event) => void submit(event)}>
      <div className="rename__row">
        <input
          ref={field}
          className="field rename__field"
          value={draft}
          autoFocus
          aria-label="Workbook filename"
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              cancel();
            }
          }}
        />
        <span className="rename__suffix mono">{WORKBOOK_SUFFIX}</span>
        <button type="submit" className="button button--primary" disabled={busy || draft.trim() === ""}>
          {busy ? "Renaming…" : "Save"}
        </button>
        <button type="button" className="button" onClick={cancel}>
          Cancel
        </button>
      </div>
      <p className="rename__preview">
        Saves as <strong>{draft.trim() === "" ? "—" : `${draft.trim()}${WORKBOOK_SUFFIX}`}</strong>
      </p>
    </form>
  );
}
