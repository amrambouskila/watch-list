import { useState, type FormEvent, type ReactElement } from "react";

import { useAppDispatch } from "../hooks/useAppDispatch";
import { addCategory } from "../stores/categorySlice";
import { loadCatalog } from "../stores/catalogSlice";
import { selectCategory, setNewCategoryOpen } from "../stores/uiSlice";
import { Modal } from "./Modal";

/** Drawn from the accents the existing workbooks already use. */
const ACCENTS: readonly { hex: string; name: string }[] = [
  { hex: "#C2410C", name: "Burnt orange" },
  { hex: "#B91C1C", name: "Red" },
  { hex: "#1D4ED8", name: "Blue" },
  { hex: "#1E3A8A", name: "Navy" },
  { hex: "#14532D", name: "Forest green" },
  { hex: "#065F46", name: "Teal" },
  { hex: "#7C2D12", name: "Brown" },
  { hex: "#6D28D9", name: "Violet" },
  { hex: "#1F2937", name: "Slate" },
];

const DEFAULT_ACCENT = ACCENTS[0]?.hex ?? "#1F2937";

export function NewCategoryDialog(): ReactElement {
  const dispatch = useAppDispatch();
  const [name, setName] = useState("");
  const [accent, setAccent] = useState(DEFAULT_ACCENT);
  const [titles, setTitles] = useState("");
  const [busy, setBusy] = useState(false);

  const close = (): void => {
    dispatch(setNewCategoryOpen(false));
  };

  const submit = async (event: FormEvent): Promise<void> => {
    event.preventDefault();
    if (name.trim() === "" || busy) return;
    setBusy(true);
    const result = await dispatch(
      addCategory({
        name: name.trim(),
        accent,
        titles: titles
          .split("\n")
          .map((line) => line.trim())
          .filter((line) => line !== ""),
      }),
    );
    setBusy(false);
    if (addCategory.fulfilled.match(result)) {
      await dispatch(loadCatalog());
      dispatch(selectCategory(result.payload.id));
      dispatch(setNewCategoryOpen(false));
    }
  };

  return (
    <Modal title="New category" onClose={close}>
      <form onSubmit={(event) => void submit(event)}>
        <p className="dialog__hint">
          Creates a workbook in the library folder with the same columns, dropdowns, and highlighting the
          existing sheets use. You can keep editing it in Excel.
        </p>

        <label className="dialog__field">
          <span className="dialog__label">Name</span>
          <input
            className="field"
            value={name}
            placeholder="Cowboy Bebop"
            onChange={(event) => setName(event.target.value)}
          />
        </label>

        <div className="dialog__field">
          <span className="dialog__label">Accent</span>
          <div className="swatches" role="group" aria-label="Accent colour">
            {ACCENTS.map((option) => (
              <button
                key={option.hex}
                type="button"
                className="swatch"
                style={{ background: option.hex }}
                aria-label={option.name}
                aria-pressed={accent === option.hex}
                onClick={() => setAccent(option.hex)}
              />
            ))}
          </div>
        </div>

        <label className="dialog__field">
          <span className="dialog__label">Entries, one per line (optional)</span>
          <textarea
            className="field"
            rows={5}
            value={titles}
            placeholder={"Cowboy Bebop\nCowboy Bebop: The Movie"}
            onChange={(event) => setTitles(event.target.value)}
          />
        </label>

        <div className="dialog__actions">
          <button type="button" className="button" onClick={close}>
            Cancel
          </button>
          <button type="submit" className="button button--primary" disabled={name.trim() === "" || busy}>
            {busy ? "Creating…" : "Create category"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
