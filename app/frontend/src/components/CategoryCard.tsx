import type { ReactElement } from "react";

import type { CategorySummary } from "../types/CategorySummary";
import { accentPalette } from "../utils/accentPalette";
import { progressPercent } from "../utils/progressPercent";
import { CategoryHero } from "./CategoryHero";

interface CategoryCardProps {
  readonly category: CategorySummary;
  readonly onOpen: () => void;
}

export function CategoryCard({ category, onOpen }: CategoryCardProps): ReactElement {
  const palette = accentPalette(category.accent, category.id);
  const percent = progressPercent(category.counts);
  const { counts } = category;

  return (
    <li>
      <button
        type="button"
        className="card"
        onClick={onOpen}
        style={{
          ["--accent" as string]: palette.accent,
          ["--accent-dim" as string]: palette.dim,
          ["--accent-soft" as string]: palette.soft,
        }}
      >
        <span className="card__hero">
          <CategoryHero
            seed={category.id}
            palette={palette}
            imageUrl={category.hero_url}
            alt=""
          />
          <span className="card__scrim" />
          <span className="card__name">{category.name}</span>
          {category.locked_by_excel && <span className="card__badge">Open in Excel</span>}
        </span>

        <span className="card__body">
          <span className="card__stats">
            <span className="card__count mono">{counts.watched}</span>
            <span className="card__of mono">/ {counts.trackable} watched</span>
            <span className="card__percent mono">{percent}%</span>
          </span>
          <span className="card__meter">
            <span style={{ width: `${percent}%` }} />
          </span>
          <span className="card__foot">
            {counts.total} entries
            {counts.in_progress > 0 && ` · ${counts.in_progress} watching`}
            {counts.skipped > 0 && ` · ${counts.skipped} skipped`}
          </span>
        </span>
      </button>
    </li>
  );
}
