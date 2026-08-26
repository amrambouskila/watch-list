import { aProbeLibrary, type ProbeLibrary } from "./aProbeLibrary";

/** A library where a second file derives the id the open category already answers to. */
export function aLibraryWithAShadowedFile(): ProbeLibrary {
  const library = aProbeLibrary();
  return {
    detail: library.detail,
    listing: {
      ...library.listing,
      shadowed: [
        {
          file_name: "A  Long  Watch  Order.xlsx",
          category_id: library.detail.id,
          answered_by: library.detail.file_name,
        },
      ],
    },
  };
}
