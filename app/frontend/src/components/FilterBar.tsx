import type { ReactElement } from "react";

import { useAppDispatch } from "../hooks/useAppDispatch";
import { setFilter, setQuery, setReferenceOpen } from "../stores/uiSlice";
import type { CategoryDetail } from "../types/CategoryDetail";
import { WATCH_FILTER_LABELS, WATCH_FILTERS, type WatchFilter } from "../types/WatchFilter";

interface FilterBarProps {
  readonly detail: CategoryDetail;
  readonly filter: WatchFilter;
  readonly query: string;
  readonly onAddEntry: () => void;
}

function countFor(detail: CategoryDetail, filter: WatchFilter): number {
  switch (filter) {
    case "all":
      return detail.counts.total;
    case "unwatched":
      return detail.counts.unwatched;
    case "in-progress":
      return detail.counts.in_progress;
    case "watched":
      return detail.counts.watched;
    case "skipped":
      return detail.counts.skipped;
  }
}

export function FilterBar({ detail, filter, query, onAddEntry }: FilterBarProps): ReactElement {
  const dispatch = useAppDispatch();

  return (
    <div className="controls">
      <div className="chips" role="group" aria-label="Filter entries by status">
        {WATCH_FILTERS.map((option) => (
          <button
            key={option}
            type="button"
            className="chip"
            aria-pressed={filter === option}
            onClick={() => dispatch(setFilter(option))}
          >
            {WATCH_FILTER_LABELS[option]}
            <span className="chip__count">{countFor(detail, option)}</span>
          </button>
        ))}
      </div>
      <div className="controls__search">
        <input
          className="field"
          type="search"
          value={query}
          placeholder={`Search ${detail.name}`}
          aria-label={`Search entries in ${detail.name}`}
          onChange={(event) => dispatch(setQuery(event.target.value))}
        />
      </div>
      <div className="controls__spacer" />
      <button type="button" className="button" onClick={onAddEntry}>
        Add entry
      </button>
      {detail.reference_sheets.length > 0 && (
        <button type="button" className="button" onClick={() => dispatch(setReferenceOpen(true))}>
          Sheet notes
        </button>
      )}
    </div>
  );
}
