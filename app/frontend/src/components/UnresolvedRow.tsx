import type { ReactElement } from "react";

import { useAppDispatch } from "../hooks/useAppDispatch";
import { useAppSelector } from "../hooks/useAppSelector";
import { confirmEntry } from "../stores/reviewSlice";
import type { CuratedEntryRead } from "../types/CuratedEntryRead";
import { resolutionStateLabel } from "../utils/resolutionStateLabel";
import { RetryResolutionButton } from "./RetryResolutionButton";

/** Fixed, for the same reason the retry's is: the label moves while the write is out, the name must not. */
const CONFIRM = "Confirm";
const CONFIRMING = "Confirming…";
/**
 * Real text in a `visually-hidden` span rather than an `aria-label` on a generic element.
 *
 * `aria-label` on a `<span>` is only honoured by some assistive technology, and it is invisible to
 * translation and to find-in-page. The number beside it is bare on purpose: the word is what says what
 * the number is, and the sheet's own `Order` cell often spells the same digit two lines below.
 */
const POSITION = "Curated position";
const IN = "in";
/** A row may carry no title at all — four of the nineteen workbooks leave cells empty all over. */
const UNTITLED = "An entry with no title";
/** Two decimals, because the queue is ordered by this number and 0.65 and 0.50 must not read alike. */
const CONFIDENCE_DECIMALS = 2;

interface UnresolvedRowProps {
  readonly entry: CuratedEntryRead;
}

/**
 * One row a heuristic could not settle, as a reviewer has to read it.
 *
 * The sheet's own cells are the whole of what is shown, verbatim and keyed the way the sheet keys
 * them: an unresolved row is a first-class row, and the text a person typed is what they judge from.
 * The workbook it came from is named beside its position (R82): the queue spans every category at
 * once, so a row with no category on it is a row a reviewer cannot go and look at.
 * Every value here is rendered as text — a note and a cell are both free text from outside this app.
 *
 * The note is shown exactly as it stands, with no history behind it (Ruling 48): a re-resolve replaces
 * it wholesale, so it says why the row is here now rather than what was decided about it before.
 */
export function UnresolvedRow({ entry }: UnresolvedRowProps): ReactElement {
  const dispatch = useAppDispatch();
  const busy = useAppSelector((state) => state.review.busy.includes(entry.id));

  return (
    <li className="unresolved__row" aria-label={entry.raw_title || UNTITLED}>
      <div className="unresolved__head">
        <span className="unresolved__position mono">
          <span className="visually-hidden">{`${POSITION} `}</span>
          {entry.position}
        </span>
        <span className="unresolved__category">
          <span className="visually-hidden">{`${IN} `}</span>
          {entry.category_slug}
        </span>
        <span className="unresolved__state">{resolutionStateLabel(entry.resolution_state)}</span>
        {entry.resolution_confidence !== null && (
          <span className="unresolved__confidence mono">
            {entry.resolution_confidence.toFixed(CONFIDENCE_DECIMALS)}
          </span>
        )}
      </div>

      <dl className="unresolved__cells">
        {Object.entries(entry.cells).map(([key, value]) => (
          <div className="unresolved__cell" key={key}>
            <dt className="eyebrow">{key}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>

      {entry.resolution_note !== "" && <p className="unresolved__note">{entry.resolution_note}</p>}

      <div className="unresolved__actions">
        <button
          type="button"
          className="button button--primary"
          aria-label={CONFIRM}
          disabled={busy}
          onClick={() => void dispatch(confirmEntry(entry.id))}
        >
          {busy ? CONFIRMING : CONFIRM}
        </button>
        <RetryResolutionButton entryId={entry.id} />
      </div>
    </li>
  );
}
