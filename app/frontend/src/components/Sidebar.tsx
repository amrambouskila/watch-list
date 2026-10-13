import type { ReactElement } from "react";

import { useAppDispatch } from "../hooks/useAppDispatch";
import { useAppSelector } from "../hooks/useAppSelector";
import { useFilteredCategories } from "../hooks/useFilteredCategories";
import { goHome, goToUnresolved, selectCategory, setCategoryQuery, setNewCategoryOpen } from "../stores/uiSlice";
import { CategoryLink } from "./CategoryLink";
import { ProviderAttribution } from "./ProviderAttribution";

/** The review queue is a screen of its own, so it is named in the nav rather than buried in a category. */
const NEEDS_REVIEW = "Needs review";

export function Sidebar(): ReactElement {
  const dispatch = useAppDispatch();
  const listing = useAppSelector((state) => state.catalog.listing);
  const activeId = useAppSelector((state) => state.ui.activeCategoryId);
  const query = useAppSelector((state) => state.ui.categoryQuery);
  const view = useAppSelector((state) => state.ui.view);

  const categories = useFilteredCategories();

  return (
    <nav className="sidebar" aria-label="Watch order library">
      <div className="sidebar__masthead">
        <button type="button" className="sidebar__wordmark" onClick={() => dispatch(goHome())}>
          Watch List
        </button>
        <p className="sidebar__path">{listing?.library_dir ?? "Reading the library…"}</p>
      </div>

      <div className="sidebar__nav">
        <button
          type="button"
          className="sidebar__nav-entry"
          aria-current={view === "unresolved"}
          onClick={() => dispatch(goToUnresolved())}
        >
          <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">
            <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeWidth="1.6" />
            <path d="M8 4.8v4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            <circle cx="8" cy="11.3" r="0.9" fill="currentColor" />
          </svg>
          {NEEDS_REVIEW}
        </button>
      </div>

      <div className="sidebar__search">
        <input
          className="field"
          type="search"
          value={query}
          placeholder="Find a category"
          aria-label="Find a category"
          onChange={(event) => dispatch(setCategoryQuery(event.target.value))}
        />
      </div>

      <ul className="sidebar__list scroll">
        {categories.map((category) => (
          <CategoryLink
            key={category.id}
            category={category}
            active={category.id === activeId}
            onSelect={() => dispatch(selectCategory(category.id))}
          />
        ))}
        {listing !== null && categories.length === 0 && (
          <li className="unreadable">No category matches that name.</li>
        )}
        {(listing?.unreadable ?? []).map((item) => (
          <li className="unreadable" key={item.file_name}>
            <strong>{item.file_name}</strong>
            Could not be opened as a workbook. {item.reason}
          </li>
        ))}
        {(listing?.shadowed ?? []).map((item) => (
          <li className="unreadable" key={item.file_name}>
            <strong>{item.file_name}</strong>
            Hidden: {item.answered_by} already answers to {item.category_id}.
          </li>
        ))}
      </ul>

      <div className="sidebar__footer">
        <button type="button" className="button button--wide" onClick={() => dispatch(setNewCategoryOpen(true))}>
          New category
        </button>
        {/* Every screen has the sidebar, so mounting it here is what puts the providers' notices
            wherever their metadata is shown, under this app's own wordmark rather than beside it. */}
        <ProviderAttribution />
      </div>
    </nav>
  );
}
