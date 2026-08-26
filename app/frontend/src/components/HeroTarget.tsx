import type { ReactElement } from "react";

import { useAccent } from "../hooks/useAccent";
import type { CategorySummary } from "../types/CategorySummary";
import { CategoryHero } from "./CategoryHero";

const UNLISTED = "not in the library listing";
const NO_ARTWORK_YET = "No artwork yet";

interface HeroTargetProps {
  readonly categoryId: string;
  /** The library's entry for that id, or null while the listing has not been read. */
  readonly category: CategorySummary | null;
}

/**
 * Which card a pick would repaint, and what that card is painted with today.
 *
 * A hero proposal carries only a category id, and a summary reading "artwork for Naruto" can carry
 * a different one — so the card's own name and its standing artwork are both on screen before the
 * click, rather than a slug the eye cannot check the summary against.
 */
export function HeroTarget({ categoryId, category }: HeroTargetProps): ReactElement {
  const palette = useAccent(category?.accent, categoryId);

  return (
    <section className="hero-target" aria-label="The card this artwork would replace">
      <div className="hero-target__frame">
        <CategoryHero
          seed={categoryId}
          palette={palette}
          imageUrl={category?.hero_url}
          alt={`Artwork on the ${category?.name ?? categoryId} card today`}
        />
      </div>
      <div className="hero-target__naming">
        <p className="eyebrow">Replacing the artwork on</p>
        <p className="hero-target__name">{category?.name ?? categoryId}</p>
        <p className="hero-target__id mono">{category === null ? UNLISTED : categoryId}</p>
        {category !== null && !category.hero_url && <p className="hero-target__empty">{NO_ARTWORK_YET}</p>}
      </div>
    </section>
  );
}
