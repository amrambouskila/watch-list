export type ToastTone = "error" | "info";

export interface Toast {
  playbackSnapshotId?: string;
  id: string;
  tone: ToastTone;
  message: string;
}
