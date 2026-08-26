import type { HeroCandidate } from "./HeroCandidate";

/** Artwork is a taste call, so this arm offers images to pick between rather than a diff to approve. */
export interface ProposalHero {
  kind: "hero";
  category_id: string;
  candidates: HeroCandidate[];
}
