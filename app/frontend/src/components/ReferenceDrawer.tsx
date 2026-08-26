import { useCallback, type ReactElement } from "react";

import { useAppDispatch } from "../hooks/useAppDispatch";
import { useFocusTrap } from "../hooks/useFocusTrap";
import { setReferenceOpen } from "../stores/uiSlice";
import type { ReferenceSheet } from "../types/ReferenceSheet";

interface ReferenceDrawerProps {
  readonly title: string;
  readonly sheets: readonly ReferenceSheet[];
}

function Value({ text }: { readonly text: string }): ReactElement {
  if (!text.startsWith("http")) return <>{text}</>;
  return (
    <a href={text} target="_blank" rel="noreferrer noopener">
      {text}
    </a>
  );
}

/** The workbook's supporting sheets, read-only — they are notes, not tracking data. */
export function ReferenceDrawer({ title, sheets }: ReferenceDrawerProps): ReactElement {
  const dispatch = useAppDispatch();
  const close = useCallback((): void => {
    dispatch(setReferenceOpen(false));
  }, [dispatch]);
  const panel = useFocusTrap<HTMLElement>(close);

  return (
    <aside className="drawer" role="dialog" aria-modal="true" aria-label={`${title} sheet notes`} ref={panel}>
      <div className="drawer__head">
        <div>
          <span className="eyebrow">Sheet notes</span>
          <h2 className="dialog__title">{title}</h2>
        </div>
        <button type="button" className="button" onClick={close}>
          Close
        </button>
      </div>
      <div className="drawer__body scroll">
        {sheets.map((sheet) => (
          <table className="sheet-table" key={sheet.title}>
            <caption>{sheet.title}</caption>
            <thead>
              <tr>
                {sheet.header.map((heading, index) => (
                  <th key={`${sheet.title}-h-${index}`} scope="col">
                    {heading}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sheet.rows.map((row, rowIndex) => (
                <tr key={`${sheet.title}-r-${rowIndex}`}>
                  {row.map((value, cellIndex) => (
                    <td key={`${sheet.title}-r-${rowIndex}-c-${cellIndex}`}>
                      <Value text={value} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        ))}
      </div>
    </aside>
  );
}
