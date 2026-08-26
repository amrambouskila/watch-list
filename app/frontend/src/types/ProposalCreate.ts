/** The workbook a create proposal would generate, in the backend CategoryCreate shape. */
export interface ProposedCategory {
  name: string;
  accent: string;
  columns: string[];
  titles: string[];
  rows: Record<string, string>[];
}

export interface ProposalCreate {
  kind: "create";
  category: ProposedCategory;
}
