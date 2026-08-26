import type { CategoryDetail } from "../types/CategoryDetail";
import { request } from "./request";

/** Hand the backend the candidate the user picked; it downloads, checks and writes the file. */
export function chooseHero(proposalId: string, choice: number): Promise<CategoryDetail> {
  return request<CategoryDetail>(`/api/chat/proposals/${encodeURIComponent(proposalId)}/hero/${choice}`, {
    method: "POST",
  });
}
