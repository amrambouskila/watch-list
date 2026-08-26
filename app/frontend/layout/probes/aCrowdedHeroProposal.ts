import type { HeroCandidate } from "../../src/types/HeroCandidate";
import type { Proposal } from "../../src/types/Proposal";
import { aHeroBody } from "../../tests/support/aProposalBody";
import { aHeroCandidate } from "../../tests/support/aHeroCandidate";
import { aProposal } from "../../tests/support/aProposal";

const CANDIDATE_COUNT = 6;
/** Served by the probe's own dev server: a candidate image must never leave this origin. */
const STUB_ARTWORK = "/stub-artwork.png";
const A_LONG_DESCRIPTION =
  "The series wordmark as it appears on the first-edition box set, knocked out of its plate so " +
  "the letterforms sit on the card's own ground rather than a white rectangle.";

function aCandidate(index: number): HeroCandidate {
  return aHeroCandidate({
    url: `${window.location.origin}${STUB_ARTWORK}?candidate=${index}`,
    source_file: `The Long Way Round wordmark, first edition, plate ${index}.png`,
    licence: "CC BY-SA 4.0 (Wikimedia Commons)",
    page: `https://example.invalid/wiki/File:Wordmark_plate_${index}.png`,
    description: `${A_LONG_DESCRIPTION} (plate ${index})`,
  });
}

/**
 * More artwork than fits the row, with prose long enough to make each card tall.
 *
 * This is the shape that once pushed every "Use this one" out of the scroller's clip at 1280x720.
 */
export function aCrowdedHeroProposal(): Proposal {
  return aProposal(aHeroBody(Array.from({ length: CANDIDATE_COUNT }, (_, index) => aCandidate(index + 1))), {
    summary: "Six freely-licensed marks for this category's card, all from Wikimedia Commons.",
  });
}
