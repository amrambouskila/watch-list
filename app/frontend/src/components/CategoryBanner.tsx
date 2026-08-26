import type { ReactElement } from "react";

import { useAppDispatch } from "../hooks/useAppDispatch";
import { goHome } from "../stores/uiSlice";
import type { CategoryDetail } from "../types/CategoryDetail";
import { progressPercent } from "../utils/progressPercent";
import { summarise } from "../utils/summarise";
import { CategoryTitle } from "./CategoryTitle";

interface CategoryBannerProps {
  readonly detail: CategoryDetail;
  readonly onRetire: () => void;
}

export function CategoryBanner({ detail, onRetire }: CategoryBannerProps): ReactElement {
  const dispatch = useAppDispatch();
  const percent = progressPercent(detail.counts);
  return (
    <header className="banner">
      <div className="banner__source">
        <button type="button" className="banner__back" onClick={() => dispatch(goHome())}>
          All categories
        </button>
        <span className="eyebrow" title={detail.file_name}>
          {detail.sheet_title}
        </span>
        <button type="button" className="banner__retire" onClick={onRetire}>
          Retire category
        </button>
      </div>
      <CategoryTitle detail={detail} />
      <p className="banner__tally">{summarise(detail.counts)}</p>
      <div className="banner__progress">
        <div
          className="banner__track"
          role="progressbar"
          aria-valuenow={percent}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`${detail.name} watch progress`}
        >
          <span style={{ width: `${percent}%` }} />
        </div>
        <span className="banner__percent">{percent}%</span>
      </div>
    </header>
  );
}
