import type { Proposal } from "../../src/types/Proposal";
import { aCreateBody } from "../../tests/support/aProposalBody";
import { aProposal } from "../../tests/support/aProposal";

const ROW_COUNT = 40;
const A_SOURCE = "https://example.invalid/watch-orders/the-crossing/chronology";

function aProposedRow(index: number): Record<string, string> {
  return {
    Title: `The Crossing, Part ${index}: A Title Long Enough To Need The Whole Column`,
    Year: String(1960 + index),
    Notes: `Placed ${index} by broadcast date, ahead of the two entries the box set reorders.`,
  };
}

/** A brand-new sheet: the same diff, with no sheet behind it for the "Now" column to read. */
export function aNewCategoryProposal(): Proposal {
  return aProposal(
    aCreateBody(
      Array.from({ length: ROW_COUNT }, (_, index) => aProposedRow(index + 1)),
      "The Crossing",
    ),
    { summary: `Builds a new category of ${ROW_COUNT} entries in broadcast order.`, sources: [A_SOURCE] },
  );
}
