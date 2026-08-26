/** What the sheet a pending edit targets holds right now, so a diff can say what it will overwrite. */
export interface StandingRows {
  status: "loading" | "ready" | "failed";
  /** The column that identifies a row to a reader; null until the sheet has been read. */
  identifyingKey: string | null;
  /** Every row's cells as they stand today, keyed by the row number a proposal would name. */
  cellsByRow: Readonly<Record<number, Readonly<Record<string, string>>>>;
}
