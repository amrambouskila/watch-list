import { aProbeLibrary, type ProbeLibrary } from "./aProbeLibrary";

/**
 * The reason really carried up from the backend: an exception's class name and the whole of its
 * message, wrapped by nothing, in a list that has to hold it without pushing the wall off screen.
 */
const A_REASON =
  "InvalidFileException: openpyxl does not support the old .xls file format, please use xlrd to " +
  "read this file, or convert it to the more recent .xlsx file format.";

/** A library holding two files the app opened and could not read, which the owner has to be told. */
export function aLibraryWithFilesItCannotOpen(): ProbeLibrary {
  const library = aProbeLibrary();
  return {
    detail: library.detail,
    listing: {
      ...library.listing,
      unreadable: [
        { file_name: "A Watch Order Saved As The Wrong Thing.xls", reason: A_REASON },
        { file_name: "~$A Long Watch Order.xlsx", reason: A_REASON },
      ],
    },
  };
}
