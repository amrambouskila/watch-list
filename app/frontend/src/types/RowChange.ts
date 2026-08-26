export type RowChangeKind = "add" | "revise" | "move" | "remove";

export interface RowChange {
  kind: RowChangeKind;
  /** Absent, not null, when the change targets no existing row: the stream omits empty fields. */
  row?: number;
  after_row?: number;
  cells: Record<string, string>;
  reason: string;
}
