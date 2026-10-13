import { useEffect, type ReactElement } from "react";

import { useAppDispatch } from "../hooks/useAppDispatch";
import { useAppSelector } from "../hooks/useAppSelector";
import { loadReviewQueue } from "../stores/reviewSlice";
import { goHome } from "../stores/uiSlice";
import { entryCount } from "../utils/entryCount";
import { UnresolvedRow } from "./UnresolvedRow";

const TITLE = "Needs review";
const BACK = "All categories";
const READING = "Reading the review queue…";
const FAILED = "The review queue could not be read.";
const TRY_AGAIN = "Try again";
const EMPTY_HEADLINE = "Nothing is waiting for review.";
const EMPTY_BODY =
  "Every row of every watch order has either been resolved or been judged by hand. New rows arrive here " +
  "when a workbook changes and a heuristic cannot settle what one of its rows means.";
/**
 * The review queue, across every category at once — `AppView` `"unresolved"`.
 *
 * It is a view of its own rather than a tab inside a category because the question it answers is
 * "what is still unreviewed", and that spans the whole library. The listing is the Phase 1 review
 * API (`GET /api/review/entries`, R71): `unresolved` and `auto` rows on live entries of categories
 * that have not been retired, worst first.
 *
 * An empty queue is the normal resting state — the dry run measured 166 rows, which is a number a
 * person works down to zero — so it says so rather than rendering nothing.
 */
export function UnresolvedView(): ReactElement {
  const dispatch = useAppDispatch();
  const entries = useAppSelector((state) => state.review.entries);
  const status = useAppSelector((state) => state.review.status);

  // The queue is this view's own data, unlike the catalog, which the sidebar needs on every screen.
  useEffect(() => {
    void dispatch(loadReviewQueue());
  }, [dispatch]);

  return (
    <section className="stage scroll unresolved">
      <header className="banner">
        {/* Inside `.banner__source`, as the category banner has it: the row that holds a back link is
            the one the stylesheet lays out, and a bare button here would sit at the wrong height. */}
        <div className="banner__source">
          <button type="button" className="banner__back" onClick={() => dispatch(goHome())}>
            {BACK}
          </button>
        </div>
        <h1 className="banner__title">{TITLE}</h1>
        <p className="banner__tally">{`${entryCount(entries.length)} a heuristic could not settle`}</p>
      </header>

      {status === "loading" && entries.length === 0 && <div className="empty">{READING}</div>}

      {status === "failed" && entries.length === 0 && (
        <div className="empty">
          <p className="empty__headline">{FAILED}</p>
          <p>
            <button type="button" className="link" onClick={() => void dispatch(loadReviewQueue())}>
              {TRY_AGAIN}
            </button>
          </p>
        </div>
      )}

      {status === "ready" && entries.length === 0 && (
        <div className="empty">
          <p className="empty__headline">{EMPTY_HEADLINE}</p>
          <p>{EMPTY_BODY}</p>
        </div>
      )}

      {entries.length > 0 && (
        <ul className="unresolved__list">
          {entries.map((entry) => (
            <UnresolvedRow key={entry.id} entry={entry} />
          ))}
        </ul>
      )}
    </section>
  );
}
