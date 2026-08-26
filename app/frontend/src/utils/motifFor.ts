export interface MotifCircle {
  cx: number;
  cy: number;
  r: number;
  width: number;
  opacity: number;
  filled: boolean;
}

export interface MotifLine {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  width: number;
  opacity: number;
}

export interface MotifPolygon {
  points: string;
  width: number;
  opacity: number;
  filled: boolean;
}

export interface MotifPath {
  d: string;
  width: number;
  opacity: number;
}

export interface Motif {
  circles: MotifCircle[];
  lines: MotifLine[];
  polygons: MotifPolygon[];
  paths: MotifPath[];
  /** Per-category rotation, scale and offset, so two cards on the same motif never match. */
  transform: string;
}

const WIDTH = 480;
const HEIGHT = 270;

function empty(): Motif {
  return { circles: [], lines: [], polygons: [], paths: [], transform: "" };
}

/** Concentric rings radiating from the lower left. */
function rings(): Motif {
  const motif = empty();
  for (let index = 0; index < 7; index += 1) {
    motif.circles.push({
      cx: 96,
      cy: 214,
      r: 34 + index * 40,
      width: index === 0 ? 0 : 1.4,
      opacity: 0.5 - index * 0.055,
      filled: index === 0,
    });
  }
  return motif;
}

/** Scattered points with a few long streaks across them. */
function starfield(): Motif {
  const motif = empty();
  const points = [
    [58, 44], [132, 96], [204, 36], [286, 118], [352, 58], [418, 148],
    [92, 178], [168, 226], [244, 194], [326, 232], [402, 208], [446, 82],
  ];
  points.forEach(([cx, cy], index) => {
    motif.circles.push({
      cx: cx ?? 0,
      cy: cy ?? 0,
      r: index % 3 === 0 ? 2.6 : 1.5,
      width: 0,
      opacity: index % 3 === 0 ? 0.75 : 0.4,
      filled: true,
    });
  });
  motif.lines.push(
    { x1: 20, y1: 232, x2: 190, y2: 150, width: 1.2, opacity: 0.35 },
    { x1: 268, y1: 246, x2: 462, y2: 128, width: 1.2, opacity: 0.25 },
  );
  return motif;
}

/** Steep diagonal speed lines. */
function speedLines(): Motif {
  const motif = empty();
  for (let index = 0; index < 11; index += 1) {
    const offset = index * 52 - 120;
    motif.lines.push({
      x1: offset,
      y1: HEIGHT + 20,
      x2: offset + 190,
      y2: -20,
      width: index % 3 === 0 ? 5 : 2,
      opacity: index % 3 === 0 ? 0.3 : 0.16,
    });
  }
  return motif;
}

/** A staggered hexagon lattice fading to the right. */
function hexGrid(): Motif {
  const motif = empty();
  const hex = (cx: number, cy: number, size: number): string =>
    Array.from({ length: 6 }, (_, corner) => {
      const angle = (Math.PI / 3) * corner - Math.PI / 6;
      return `${(cx + size * Math.cos(angle)).toFixed(1)},${(cy + size * Math.sin(angle)).toFixed(1)}`;
    }).join(" ");

  for (let column = 0; column < 8; column += 1) {
    for (let row = 0; row < 4; row += 1) {
      const cx = 40 + column * 62;
      const cy = 40 + row * 66 + (column % 2 === 0 ? 0 : 33);
      motif.polygons.push({
        points: hex(cx, cy, 26),
        width: 1.3,
        opacity: Math.max(0.05, 0.4 - column * 0.045),
        filled: false,
      });
    }
  }
  return motif;
}

/** Stacked swells rolling across the lower half. */
function waves(): Motif {
  const motif = empty();
  for (let index = 0; index < 5; index += 1) {
    const base = 130 + index * 30;
    motif.paths.push({
      d: `M -20 ${base} C 80 ${base - 42}, 160 ${base + 38}, 250 ${base - 6} S 420 ${base - 46}, 500 ${base + 4}`,
      width: index === 0 ? 3 : 1.6,
      opacity: 0.42 - index * 0.06,
    });
  }
  return motif;
}

/** A ridgeline of overlapping peaks. */
function peaks(): Motif {
  const motif = empty();
  const ranges = [
    { base: 250, points: [[-20, 250], [90, 120], [180, 250]], opacity: 0.16 },
    { base: 250, points: [[110, 250], [232, 76], [354, 250]], opacity: 0.26 },
    { base: 250, points: [[280, 250], [386, 138], [500, 250]], opacity: 0.2 },
  ];
  ranges.forEach((range) => {
    motif.polygons.push({
      points: range.points.map(([x, y]) => `${x},${y}`).join(" "),
      width: 0,
      opacity: range.opacity,
      filled: true,
    });
  });
  motif.lines.push({ x1: -20, y1: 250, x2: 500, y2: 250, width: 1.5, opacity: 0.4 });
  return motif;
}

/** A halftone field that thins out toward the top right. */
function halftone(): Motif {
  const motif = empty();
  for (let column = 0; column < 16; column += 1) {
    for (let row = 0; row < 9; row += 1) {
      const cx = 16 + column * 31;
      const cy = 16 + row * 30;
      const falloff = 1 - (column / 16) * 0.7 - (1 - row / 9) * 0.35;
      if (falloff <= 0.06) continue;
      motif.circles.push({ cx, cy, r: 1 + falloff * 6, width: 0, opacity: falloff * 0.5, filled: true });
    }
  }
  return motif;
}

/** An equaliser of vertical bars along the base. */
function bars(): Motif {
  const motif = empty();
  const heights = [70, 132, 46, 178, 96, 210, 62, 148, 108, 186, 78, 122];
  heights.forEach((height, index) => {
    const x = 26 + index * 38;
    motif.lines.push({ x1: x, y1: HEIGHT - 16, x2: x, y2: HEIGHT - 16 - height, width: 9, opacity: 0.14 + (index % 4) * 0.06 });
  });
  return motif;
}

/** Two crossing orbits around a filled core. */
function orbits(): Motif {
  const motif = empty();
  motif.circles.push(
    { cx: 344, cy: 104, r: 22, width: 0, opacity: 0.75, filled: true },
    { cx: 344, cy: 104, r: 54, width: 1.6, opacity: 0.4, filled: false },
    { cx: 344, cy: 104, r: 92, width: 1.2, opacity: 0.22, filled: false },
  );
  motif.paths.push(
    { d: "M 150 220 C 210 120, 300 60, 452 66", width: 1.6, opacity: 0.3 },
    { d: "M 92 118 C 190 208, 320 236, 470 190", width: 1.6, opacity: 0.22 },
  );
  return motif;
}

/** A widening corridor of nested chevrons. */
function chevrons(): Motif {
  const motif = empty();
  for (let index = 0; index < 8; index += 1) {
    const spread = 30 + index * 30;
    motif.paths.push({
      d: `M ${WIDTH / 2 - spread} ${HEIGHT} L ${WIDTH / 2} ${HEIGHT - spread * 0.72} L ${WIDTH / 2 + spread} ${HEIGHT}`,
      width: 2,
      opacity: 0.34 - index * 0.035,
    });
  }
  return motif;
}

const MOTIFS: readonly (() => Motif)[] = [
  rings,
  starfield,
  speedLines,
  hexGrid,
  waves,
  peaks,
  halftone,
  bars,
  orbits,
  chevrons,
];

/** FNV-1a, so ids sharing a long boilerplate suffix still land in different buckets. */
function hash(value: string, offset = 0x811c9dc5): number {
  let result = offset;
  for (let index = 0; index < value.length; index += 1) {
    result ^= value.charCodeAt(index);
    result = Math.imul(result, 0x01000193) >>> 0;
  }
  return result >>> 0;
}

/**
 * The same category always gets the same artwork, so cards stay recognisable between sessions.
 *
 * With more categories than motifs some sharing is unavoidable, so a second hash rotates,
 * scales and offsets the geometry — two cards on the same motif still read as different art.
 */
export function motifFor(seed: string): Motif {
  const primary = hash(seed);
  const build = MOTIFS[primary % MOTIFS.length] ?? rings;
  const motif = build();

  const variant = hash(seed, 0x9e3779b1);
  const angle = ((variant % 25) - 12).toFixed(1);
  const scale = (1 + ((variant >>> 5) % 30) / 100).toFixed(2);
  const shiftX = (((variant >>> 11) % 90) - 45).toFixed(0);
  const shiftY = (((variant >>> 17) % 60) - 30).toFixed(0);
  const flip = (variant >>> 23) % 2 === 0 ? 1 : -1;

  motif.transform =
    `translate(${WIDTH / 2} ${HEIGHT / 2}) rotate(${angle}) scale(${flip * Number(scale)} ${scale}) ` +
    `translate(${-WIDTH / 2 + Number(shiftX)} ${-HEIGHT / 2 + Number(shiftY)})`;
  return motif;
}
