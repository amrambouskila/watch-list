import type { ReactElement } from "react";

import type { CategorySummary } from "../types/CategorySummary";
import { accentPalette } from "../utils/accentPalette";
import { progressPercent } from "../utils/progressPercent";

interface CategoryLinkProps {
  readonly category: CategorySummary;
  readonly active: boolean;
  readonly onSelect: () => void;
}

export function CategoryLink({ category, active, onSelect }: CategoryLinkProps): ReactElement {
  const percent = progressPercent(category.counts);
  const palette = accentPalette(category.accent, category.id);

  return (
    <li>
      <button
        type="button"
        className="category-link"
        aria-current={active}
        onClick={onSelect}
        style={{ ["--accent" as string]: palette.accent }}
      >
        <span className="category-link__top">
          <span className="category-link__name">
            {category.name}
            {category.locked_by_excel && (
              <span className="category-link__flag" title="Open in Excel — edits are paused">
                open in Excel
              </span>
            )}
          </span>
          <span className="category-link__percent">{percent}%</span>
        </span>
        <span className="category-link__meter">
          <span style={{ width: `${percent}%` }} />
        </span>
      </button>
    </li>
  );
}
