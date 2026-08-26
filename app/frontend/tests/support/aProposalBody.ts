import type { ProposalCreate } from "../../src/types/ProposalCreate";
import type { ProposalEdit } from "../../src/types/ProposalEdit";
import type { ProposalHero } from "../../src/types/ProposalHero";
import type { HeroCandidate } from "../../src/types/HeroCandidate";
import type { RowChange } from "../../src/types/RowChange";

export const A_CATEGORY_ID = "a-category";

export function anEditBody(changes: readonly RowChange[], categoryId: string = A_CATEGORY_ID): ProposalEdit {
  return { kind: "edit", category_id: categoryId, read_mtime: 1, changes: [...changes] };
}

export function aCreateBody(rows: readonly Record<string, string>[], name = "A New Category"): ProposalCreate {
  return {
    kind: "create",
    category: { name, accent: "#1F2937", columns: ["Title"], titles: ["Title"], rows: [...rows] },
  };
}

export function aHeroBody(candidates: readonly HeroCandidate[], categoryId: string = A_CATEGORY_ID): ProposalHero {
  return { kind: "hero", category_id: categoryId, candidates: [...candidates] };
}
