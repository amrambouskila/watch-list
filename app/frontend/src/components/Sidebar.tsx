import type { ReactElement } from "react";

import { useAppDispatch } from "../hooks/useAppDispatch";
import { useAppSelector } from "../hooks/useAppSelector";
import { useFilteredCategories } from "../hooks/useFilteredCategories";
import { goHome, selectCategory, setCategoryQuery, setNewCategoryOpen } from "../stores/uiSlice";
import { CategoryLink } from "./CategoryLink";

export function Sidebar(): ReactElement {
  const dispatch = useAppDispatch();
  const listing = useAppSelector((state) => state.catalog.listing);
  const activeId = useAppSelector((state) => state.ui.activeCategoryId);
  const query = useAppSelector((state) => state.ui.categoryQuery);

  const categories = useFilteredCategories();

  return (
    <nav className="sidebar" aria-label="Watch order library">
      <div className="sidebar__masthead">
        <button type="button" className="sidebar__wordmark" onClick={() => dispatch(goHome())}>
          Watch List
        </button>
        <p className="sidebar__path">{listing?.library_dir ?? "Reading the library…"}</p>
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
      </div>
    </nav>
  );
}
