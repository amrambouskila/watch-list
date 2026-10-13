export interface LibrarySyncResult {
  seen: number;
  added: number;
  updated: number;
  removed: number;
  synced_at: string;
  incremental: boolean;
}
