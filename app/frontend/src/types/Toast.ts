export type ToastTone = "error" | "info";

export interface Toast {
  id: string;
  tone: ToastTone;
  message: string;
}
