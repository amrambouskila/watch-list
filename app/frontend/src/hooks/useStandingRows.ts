import { useEffect, useState } from "react";

import { fetchCategory } from "../api/fetchCategory";
import type { StandingRows } from "../types/StandingRows";
import { standingRowsIn } from "../utils/standingRowsIn";

const UNREAD: StandingRows = { status: "loading", identifyingKey: null, cellsByRow: {} };
const UNREADABLE: StandingRows = { status: "failed", identifyingKey: null, cellsByRow: {} };

/**
 * What a category's rows hold right now, so a diff can say what each change will overwrite or delete.
 *
 * The rows are read fresh rather than taken from the open category, because a proposal can target a
 * category nobody is looking at.
 */
export function useStandingRows(categoryId: string | null): StandingRows {
  const [standing, setStanding] = useState<StandingRows>(UNREAD);

  useEffect(() => {
    if (categoryId === null) return;
    let current = true;
    setStanding(UNREAD);
    void fetchCategory(categoryId).then(
      (detail) => {
        if (current) setStanding(standingRowsIn(detail));
      },
      () => {
        if (current) setStanding(UNREADABLE);
      },
    );
    return () => {
      current = false;
    };
  }, [categoryId]);

  return standing;
}
