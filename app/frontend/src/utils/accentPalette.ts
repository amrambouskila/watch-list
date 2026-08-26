export interface AccentPalette {
  /** Readable on the dark chrome — used for text, rails, and active states. */
  readonly accent: string;
  /** Muted variant for fills behind content. */
  readonly dim: string;
  /** Translucent wash for hover and selection surfaces. */
  readonly soft: string;
}

const MIN_SATURATION = 0.12;
const ACCENT_LIGHTNESS = 0.64;
const DIM_LIGHTNESS = 0.3;
const FALLBACK_SATURATION = 0.5;

function hash(value: string): number {
  let result = 0;
  for (let index = 0; index < value.length; index += 1) {
    result = (result * 31 + value.charCodeAt(index)) % 360;
  }
  return result;
}

function toHsl(hex: string): { h: number; s: number; l: number } {
  const clean = hex.replace("#", "");
  const r = parseInt(clean.slice(0, 2), 16) / 255;
  const g = parseInt(clean.slice(2, 4), 16) / 255;
  const b = parseInt(clean.slice(4, 6), 16) / 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const delta = max - min;
  const l = (max + min) / 2;
  if (delta === 0) return { h: 0, s: 0, l };
  const s = delta / (1 - Math.abs(2 * l - 1));
  let h: number;
  if (max === r) h = ((g - b) / delta) % 6;
  else if (max === g) h = (b - r) / delta + 2;
  else h = (r - g) / delta + 4;
  return { h: (h * 60 + 360) % 360, s, l };
}

function toHex(h: number, s: number, l: number): string {
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = l - c / 2;
  const sector = Math.floor(h / 60) % 6;
  const table: readonly (readonly [number, number, number])[] = [
    [c, x, 0],
    [x, c, 0],
    [0, c, x],
    [0, x, c],
    [x, 0, c],
    [c, 0, x],
  ];
  const [r, g, b] = table[sector] ?? [c, x, 0];
  const channel = (value: number): string =>
    Math.round((value + m) * 255)
      .toString(16)
      .padStart(2, "0");
  return `#${channel(r)}${channel(g)}${channel(b)}`;
}

/**
 * Lift a workbook's own header colour into something legible on the dark chrome.
 * Near-grey headers (several sheets share #111827) get a hue derived from the
 * category name so they stay distinguishable in the sidebar.
 */
export function accentPalette(hex: string, seed: string): AccentPalette {
  const source = toHsl(hex);
  const desaturated = source.s < MIN_SATURATION;
  const h = desaturated ? hash(seed) : source.h;
  const s = desaturated ? FALLBACK_SATURATION : Math.min(Math.max(source.s, 0.45), 0.85);
  return {
    accent: toHex(h, s, ACCENT_LIGHTNESS),
    dim: toHex(h, s * 0.8, DIM_LIGHTNESS),
    soft: `${toHex(h, s, ACCENT_LIGHTNESS)}24`,
  };
}
