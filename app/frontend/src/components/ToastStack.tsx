import { useCallback, type ReactElement } from "react";

import { useAppDispatch } from "../hooks/useAppDispatch";
import { useAppSelector } from "../hooks/useAppSelector";
import { dismissToast } from "../stores/uiSlice";
import { ToastMessage } from "./ToastMessage";

export function ToastStack(): ReactElement | null {
  const dispatch = useAppDispatch();
  const toasts = useAppSelector((state) => state.ui.toasts);
  const dismiss = useCallback((id: string): void => void dispatch(dismissToast(id)), [dispatch]);

  if (toasts.length === 0) return null;

  return (
    <div className="toasts" role="status" aria-live="polite">
      {toasts.map((toast) => (
        <ToastMessage key={toast.id} toast={toast} onDismiss={dismiss} />
      ))}
    </div>
  );
}
