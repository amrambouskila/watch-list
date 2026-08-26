export type ColumnKind = "text" | "choice";
export type ColumnRole = "order" | "title" | "watch" | "other";

export interface ColumnSpec {
  key: string;
  label: string;
  index: number;
  kind: ColumnKind;
  role: ColumnRole;
  choices: string[];
  width: number | null;
}
