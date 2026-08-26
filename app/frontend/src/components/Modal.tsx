import { useId, type ReactElement, type ReactNode } from "react";

import { useFocusTrap } from "../hooks/useFocusTrap";

interface ModalProps {
  readonly title: string;
  readonly onClose: () => void;
  readonly children: ReactNode;
}

/** The shared overlay shell: labelled, focus-trapped, closable with Escape or the backdrop. */
export function Modal({ title, onClose, children }: ModalProps): ReactElement {
  const titleId = useId();
  const panel = useFocusTrap<HTMLDivElement>(onClose);

  return (
    <div className="scrim" onMouseDown={onClose}>
      <div
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        ref={panel}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <h2 className="dialog__title" id={titleId}>
          {title}
        </h2>
        {children}
      </div>
    </div>
  );
}
