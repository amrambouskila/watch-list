import { useMemo } from "react";

import { accentPalette, type AccentPalette } from "../utils/accentPalette";

export function useAccent(hex: string | undefined, seed: string | undefined): AccentPalette {
  return useMemo(() => accentPalette(hex ?? "#1F2937", seed ?? "default"), [hex, seed]);
}
