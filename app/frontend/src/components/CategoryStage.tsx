import { useState, type ReactElement } from "react";

import { useAccent } from "../hooks/useAccent";
import { useAppDispatch } from "../hooks/useAppDispatch";
import { useAppSelector } from "../hooks/useAppSelector";
import { useVisibleRows } from "../hooks/useVisibleRows";
import { useWatchColumn } from "../hooks/useWatchColumn";
import { enableWatchColumn, loadCategory } from "../stores/categorySlice";
import { AddEntryDialog } from "./AddEntryDialog";
import { CategoryBanner } from "./CategoryBanner";
import { FilterBar } from "./FilterBar";
import { ReferenceDrawer } from "./ReferenceDrawer";
import { RetireCategoryDialog } from "./RetireCategoryDialog";
import { RouteList } from "./RouteList";

export function CategoryStage(): ReactElement {
  const dispatch = useAppDispatch();
  const detail = useAppSelector((state) => state.category.detail);
  const activeId = useAppSelector((state) => state.ui.activeCategoryId);
  const status = useAppSelector((state) => state.category.status);
  const filter = useAppSelector((state) => state.ui.filter);
  const query = useAppSelector((state) => state.ui.query);
  const expandedRow = useAppSelector((state) => state.ui.expandedRow);
  const referenceOpen = useAppSelector((state) => state.ui.referenceOpen);
  const [adding, setAdding] = useState(false);
  const [retiring, setRetiring] = useState(false);

  const watch = useWatchColumn(detail);
  const rows = useVisibleRows(detail, watch, filter, query);
  const palette = useAccent(detail?.accent, detail?.id);

  if (detail === null) {
    return (
      <section className="stage">
        {status === "failed" && activeId !== null ? (
          <div className="empty">
            <p className="empty__headline">That workbook would not open</p>
            <p>It may be mid-save, moved, or not a spreadsheet.</p>
            <p>
              <button type="button" className="button" onClick={() => void dispatch(loadCategory(activeId))}>
                Try again
              </button>
            </p>
          </div>
        ) : (
          <div className="empty">{status === "loading" ? "Opening the workbook…" : "Pick a category to start."}</div>
        )}
      </section>
    );
  }

  return (
    <section
      className="stage scroll"
      style={{
        ["--accent" as string]: palette.accent,
        ["--accent-dim" as string]: palette.dim,
        ["--accent-soft" as string]: palette.soft,
      }}
    >
      <CategoryBanner detail={detail} onRetire={() => setRetiring(true)} />

      {detail.locked_by_excel && (
        <p className="notice notice--locked">
          <span>{detail.file_name} is open in Excel. Close it to save changes from here.</span>
        </p>
      )}

      {!detail.has_watch_column && (
        <div className="notice">
          <span>This sheet has no Watched? column yet, so nothing can be tracked.</span>
          <button
            type="button"
            className="button"
            onClick={() => dispatch(enableWatchColumn({ categoryId: detail.id }))}
          >
            Add one
          </button>
        </div>
      )}

      <FilterBar detail={detail} filter={filter} query={query} onAddEntry={() => setAdding(true)} />

      {rows.length === 0 ? (
        <div className="empty">
          <p className="empty__headline">Nothing matches</p>
          <p>
            {detail.counts.total === 0
              ? "This sheet has no entries yet. Add the first one."
              : "Clear the search or pick a different status."}
          </p>
        </div>
      ) : (
        <RouteList detail={detail} watch={watch} rows={rows} expandedRow={expandedRow} />
      )}

      {adding && <AddEntryDialog detail={detail} onClose={() => setAdding(false)} />}
      {retiring && <RetireCategoryDialog detail={detail} onClose={() => setRetiring(false)} />}
      {referenceOpen && <ReferenceDrawer title={detail.name} sheets={detail.reference_sheets} />}
    </section>
  );
}
