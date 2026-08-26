import { useEffect, useRef, type MutableRefObject } from "react";

const FOCUSABLE = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

/**
 * Keep keyboard focus inside an overlay while it is open.
 *
 * Focus moves to the first control on mount, Tab cycles within the panel, Escape closes, and
 * whatever was focused before the overlay opened gets focus back on close.
 *
 * The effect runs once per mount and reads `onClose` through a ref. Depending on the callback
 * directly would re-run setup on every render of the dialog — and setup focuses the first
 * control, so typing anywhere in the panel would yank the caret back to the first field.
 */
export function useFocusTrap<T extends HTMLElement>(onClose: () => void): MutableRefObject<T | null> {
  const panel = useRef<T | null>(null);
  const close = useRef(onClose);

  useEffect(() => {
    close.current = onClose;
  }, [onClose]);

  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const items = (): HTMLElement[] =>
      panel.current === null ? [] : Array.from(panel.current.querySelectorAll<HTMLElement>(FOCUSABLE));

    items()[0]?.focus();

    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === "Escape") {
        event.preventDefault();
        close.current();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = items();
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (first === undefined || last === undefined) return;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      opener?.focus();
    };
  }, []);

  return panel;
}
