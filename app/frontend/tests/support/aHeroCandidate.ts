import type { HeroCandidate } from "../../src/types/HeroCandidate";

export function aHeroCandidate(draft: Partial<HeroCandidate> = {}): HeroCandidate {
  return {
    url: "https://example.org/artwork.jpg",
    source_file: "Artwork.jpg",
    licence: "CC BY-SA 4.0",
    page: "https://example.org/artwork",
    description: "A still from the opening",
    ...draft,
  };
}
