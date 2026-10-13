import type { ReactElement } from "react";

import { useAppDispatch } from "../hooks/useAppDispatch";
import { useAppSelector } from "../hooks/useAppSelector";
import { retryEntry } from "../stores/reviewSlice";

/**
 * The name a screen reader and the layout guard both find this control by.
 *
 * Fixed rather than taken from the label, because the label changes while the search is out and a
 * control whose name moves is a control neither of them can keep hold of.
 */
const RETRY = "Retry resolution";
const WAITING = "Retrying…";

interface RetryResolutionButtonProps {
  readonly entryId: string;
}

/**
 * Ask the provider about this one row again (R71).
 *
 * It exists because an untouched workbook is skipped, so nothing re-resolves a row a provider outage
 * left `unresolved` except the next real edit — and the queue is where a person is already looking at
 * that row. One press spends one search on one row; there is deliberately no way to spend 996.
 */
export function RetryResolutionButton({ entryId }: RetryResolutionButtonProps): ReactElement {
  const dispatch = useAppDispatch();
  const busy = useAppSelector((state) => state.review.busy.includes(entryId));

  return (
    <button
      type="button"
      className="button"
      aria-label={RETRY}
      disabled={busy}
      onClick={() => void dispatch(retryEntry(entryId))}
    >
      {busy ? WAITING : RETRY}
    </button>
  );
}
