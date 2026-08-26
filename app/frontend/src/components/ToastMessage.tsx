import { useEffect, type ReactElement } from "react";

import type { Toast } from "../types/Toast";

const DISMISS_AFTER_MS = 7000;

interface ToastMessageProps {
  readonly toast: Toast;
  readonly onDismiss: (id: string) => void;
}

/** Owns its own timer, so a newer toast never resets the countdown of an older one. */
export function ToastMessage({ toast, onDismiss }: ToastMessageProps): ReactElement {
  const { id } = toast;

  useEffect(() => {
    const timer = window.setTimeout(() => onDismiss(id), DISMISS_AFTER_MS);
    return () => window.clearTimeout(timer);
  }, [id, onDismiss]);

  return (
    <div className={`toast toast--${toast.tone}`}>
      <span>{toast.message}</span>
      <button type="button" className="toast__dismiss" aria-label="Dismiss" onClick={() => onDismiss(id)}>
        ×
      </button>
    </div>
  );
}
