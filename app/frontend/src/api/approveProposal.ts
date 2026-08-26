import type { CategoryDetail } from "../types/CategoryDetail";
import { request } from "./request";

export function approveProposal(proposalId: string): Promise<CategoryDetail> {
  return request<CategoryDetail>(`/api/chat/proposals/${encodeURIComponent(proposalId)}/approve`, { method: "POST" });
}
