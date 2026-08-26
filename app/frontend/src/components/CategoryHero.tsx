import { useMemo, type ReactElement } from "react";

import type { AccentPalette } from "../utils/accentPalette";
import { motifFor } from "../utils/motifFor";

interface CategoryHeroProps {
  readonly seed: string;
  readonly palette: AccentPalette;
  readonly imageUrl: string | null | undefined;
  readonly alt: string;
}

/**
 * PNG and SVG drop-ins are treated as logo marks; photographic formats fill the card.
 *
 * The extension is read from the path alone: a hero URL carries a cache-busting query so that
 * replaced artwork actually reaches the browser, and matching against the whole string would
 * classify every logo as a photograph.
 */
function isLogo(url: string): boolean {
  const path = url.split(/[?#]/)[0] ?? "";
  return /\.(png|svg)$/i.test(path);
}

function Backdrop({ seed, palette }: { readonly seed: string; readonly palette: AccentPalette }): ReactElement {
  const motif = useMemo(() => motifFor(seed), [seed]);

  return (
    <svg className="hero__art" viewBox="0 0 480 270" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
      <defs>
        <linearGradient id={`ground-${seed}`} x1="0" y1="0" x2="0.4" y2="1">
          <stop offset="0%" stopColor={palette.dim} stopOpacity="0.85" />
          <stop offset="100%" stopColor="#0b0e13" stopOpacity="1" />
        </linearGradient>
        <radialGradient id={`glow-${seed}`} cx="0.5" cy="0.45" r="0.75">
          <stop offset="0%" stopColor={palette.accent} stopOpacity="0.5" />
          <stop offset="100%" stopColor={palette.accent} stopOpacity="0" />
        </radialGradient>
      </defs>

      <rect width="480" height="270" fill={`url(#ground-${seed})`} />
      <rect width="480" height="270" fill={`url(#glow-${seed})`} />

      <g stroke={palette.accent} fill={palette.accent} strokeLinecap="round" transform={motif.transform}>
        {motif.circles.map((circle, index) => (
          <circle
            key={`c${index}`}
            cx={circle.cx}
            cy={circle.cy}
            r={circle.r}
            fill={circle.filled ? palette.accent : "none"}
            fillOpacity={circle.filled ? circle.opacity : 0}
            strokeOpacity={circle.filled ? 0 : circle.opacity}
            strokeWidth={circle.width}
          />
        ))}
        {motif.lines.map((line, index) => (
          <line
            key={`l${index}`}
            x1={line.x1}
            y1={line.y1}
            x2={line.x2}
            y2={line.y2}
            strokeOpacity={line.opacity}
            strokeWidth={line.width}
          />
        ))}
        {motif.polygons.map((polygon, index) => (
          <polygon
            key={`p${index}`}
            points={polygon.points}
            fill={polygon.filled ? palette.accent : "none"}
            fillOpacity={polygon.filled ? polygon.opacity : 0}
            strokeOpacity={polygon.filled ? 0 : polygon.opacity}
            strokeWidth={polygon.width}
          />
        ))}
        {motif.paths.map((path, index) => (
          <path key={`d${index}`} d={path.d} fill="none" strokeOpacity={path.opacity} strokeWidth={path.width} />
        ))}
      </g>
    </svg>
  );
}

/**
 * Artwork for a category card.
 *
 * The backdrop is original geometry composed from the workbook's own accent colour — a motif
 * picked from the category id, then rotated and scaled by a second hash so that two categories
 * sharing a motif still read as different art. A logo dropped into app/heroes sits on top of
 * it; a photograph replaces it outright.
 */
export function CategoryHero({ seed, palette, imageUrl, alt }: CategoryHeroProps): ReactElement {
  if (imageUrl && !isLogo(imageUrl)) {
    return <img className="hero__image" src={imageUrl} alt={alt} loading="lazy" />;
  }

  return (
    <>
      <Backdrop seed={seed} palette={palette} />
      {imageUrl && <img className="hero__logo" src={imageUrl} alt={alt} loading="lazy" />}
    </>
  );
}
