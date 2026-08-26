import type { ProposalCreate } from "./ProposalCreate";
import type { ProposalEdit } from "./ProposalEdit";
import type { ProposalHero } from "./ProposalHero";

export interface Proposal {
  id: string;
  summary: string;
  sources: string[];
  body: ProposalCreate | ProposalEdit | ProposalHero;
}
