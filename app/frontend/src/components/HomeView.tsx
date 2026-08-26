import { useMemo, type ReactElement } from "react";

import { useAppDispatch } from "../hooks/useAppDispatch";
import { useAppSelector } from "../hooks/useAppSelector";
import { useFilteredCategories } from "../hooks/useFilteredCategories";
import { selectCategory, setCategoryQuery, setNewCategoryOpen } from "../stores/uiSlice";
import { CategoryCard } from "./CategoryCard";

export function HomeView(): ReactElement {
  const dispatch = useAppDispatch();
  const listing = useAppSelector((state) => state.catalog.listing);
  const status = useAppSelector((state) => state.catalog.status);
  const query = useAppSelector((state) => state.ui.categoryQuery);
  const categories = useFilteredCategories();

  const totals = useMemo(() => {
    const all = listing?.categories ?? [];
    return all.reduce(
      (sum, category) => ({
        entries: sum.entries + category.counts.total,
        watched: sum.watched + category.counts.watched,
      }),
      { entries: 0, watched: 0 },
    );
  }, [listing]);

  const total = listing?.categories.length ?? 0;
  const searching = query.trim() !== "";

  return (
    <section className="stage scroll home">
      <header className="banner">
        <h1 className="banner__title">Watch List</h1>
        <p className="banner__tally">
          {searching
            ? `${categories.length} of ${total} categories`
            : `${total} categories · ${totals.entries} entries · ${totals.watched} watched`}
        </p>
        <div className="home__search">
          <input
            className="field"
            type="search"
            value={query}
            placeholder="Search categories"
            aria-label="Search categories"
            onChange={(event) => dispatch(setCategoryQuery(event.target.value))}
          />
        </div>
      </header>

      {status === "loading" && total === 0 ? (
        <div className="empty">Reading the workbooks…</div>
      ) : (
        <ul className="cards">
          {categories.map((category) => (
            <CategoryCard
              key={category.id}
              category={category}
              onOpen={() => dispatch(selectCategory(category.id))}
            />
          ))}
          {!searching && (
            <li>
              <button type="button" className="card card--new" onClick={() => dispatch(setNewCategoryOpen(true))}>
                <span className="card__plus" aria-hidden="true">
                  +
                </span>
                <span className="card__name card__name--new">Add a category</span>
                <span className="card__foot">Creates a new workbook in the library folder</span>
              </button>
            </li>
          )}
        </ul>
      )}

      {searching && categories.length === 0 && (
        <div className="empty">
          <p className="empty__headline">Nothing matches “{query.trim()}”</p>
          <p>
            <button type="button" className="link" onClick={() => dispatch(setCategoryQuery(""))}>
              Clear the search
            </button>{" "}
            to see all {total} categories.
          </p>
        </div>
      )}

      {(listing?.unreadable ?? []).length > 0 && (
        <div className="home__unreadable">
          <p className="eyebrow">Could not be opened</p>
          {(listing?.unreadable ?? []).map((item) => (
            <p key={item.file_name} className="unreadable">
              <strong>{item.file_name}</strong>
              {item.reason}
            </p>
          ))}
        </div>
      )}

      {(listing?.shadowed ?? []).length > 0 && (
        <div className="home__unreadable">
          <p className="eyebrow">Hidden by another file</p>
          {(listing?.shadowed ?? []).map((item) => (
            <p key={item.file_name} className="unreadable">
              <strong>{item.file_name}</strong>
              Its name derives the id {item.category_id}, which {item.answered_by} already answers to, so this
              file is the one the app opens for neither reading nor writing. Rename it to bring it back.
            </p>
          ))}
        </div>
      )}
    </section>
  );
}
