import { aProbeCategory } from "./aProbeCategory";
import { aProbeListing } from "./aProbeListing";
import type { ProbeLibrary } from "./aProbeLibrary";

/**
 * The library with its one category open in Excel, which the stage says so with a banner.
 *
 * The banner is a row the stage did not have a moment ago, above every control on it, so the guard
 * has to see the category at the height that banner leaves rather than only at its usual one.
 */
export function aLibraryExcelIsHolding(): ProbeLibrary {
  const detail = { ...aProbeCategory(), locked_by_excel: true };
  return { detail, listing: aProbeListing(detail) };
}
