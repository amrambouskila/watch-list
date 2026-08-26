import type { Proposal } from "../../src/types/Proposal";
import type { ProposalCreate } from "../../src/types/ProposalCreate";
import type { ProposalEdit } from "../../src/types/ProposalEdit";
import type { ProposalHero } from "../../src/types/ProposalHero";

interface ProposalDraft {
  readonly id?: string;
  readonly summary?: string;
  readonly sources?: string[];
}

export function aProposal(
  body: ProposalCreate | ProposalEdit | ProposalHero,
  draft: ProposalDraft = {},
): Proposal {
  return {
    id: draft.id ?? "a-proposal",
    summary: draft.summary ?? "A change Claude is proposing.",
    sources: draft.sources ?? [],
    body,
  };
}
