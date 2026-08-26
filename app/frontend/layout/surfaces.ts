export type SurfaceName =
  | "home"
  | "home-with-toast"
  | "category"
  | "add-entry-dialog"
  | "new-category-dialog"
  | "reference-drawer"
  | "retire-dialog"
  | "retire-dialog-with-toast"
  | "chat"
  | "chat-with-toast"
  | "edit-proposal"
  | "edit-proposal-with-toast"
  | "edit-proposal-under-a-full-toast-lane"
  | "create-proposal"
  | "hero-proposal"
  | "home-with-files-it-cannot-open"
  | "home-with-a-shadowed-file"
  | "category-excel-is-holding";

/** One screen the guard drives the real app into, and the part of it whose controls must work. */
export interface SurfaceSpec {
  readonly name: SurfaceName;
  /**
   * The region under test. Controls outside it are either covered by it on purpose — a modal
   * scrim does that — or belong to a surface of their own, so they are not this surface's promise.
   */
  readonly root: string;
  /** Controls that have to be there, so a surface that failed to render cannot pass by being empty. */
  readonly expects: readonly string[];
  /**
   * Whether a toast is up while the surface is measured.
   *
   * A toast is never inside any of these roots, so the guard checks it from both sides: the
   * surface's own controls have to survive it, and the toast has to stay on screen and dismissable.
   */
  readonly withToast: boolean;
}

const A_CATEGORY = "A Long Watch Order";
/** Every control the cards wall promises, whatever else the library made it print underneath. */
const THE_WALL = ["Watch List", "Find a category", "Search categories", "New category", "Ask Claude"];
/** Every control an open category promises, whatever else the stage had to make room for. */
const THE_CATEGORY = [
  "All categories",
  "Retire category",
  `Search entries in ${A_CATEGORY}`,
  "Add entry",
  "Sheet notes",
  "Delete entry",
];
const THE_SHELL = ".shell";
const THE_STAGE = ".stage";
const A_DIALOG = ".dialog";
const THE_DRAWER = ".drawer";
const THE_DOCK = ".chat-dock";

export const SURFACES: readonly SurfaceSpec[] = [
  {
    name: "home",
    root: THE_SHELL,
    expects: THE_WALL,
    withToast: false,
  },
  {
    name: "home-with-toast",
    root: THE_SHELL,
    expects: THE_WALL,
    withToast: true,
  },
  {
    name: "category",
    root: THE_STAGE,
    expects: THE_CATEGORY,
    withToast: false,
  },
  {
    name: "add-entry-dialog",
    root: A_DIALOG,
    expects: ["Cancel", "Add entry", "Title", "Watched?", "Notes"],
    withToast: false,
  },
  {
    name: "new-category-dialog",
    root: A_DIALOG,
    expects: ["Cancel", "Create category", "Burnt orange", "Slate"],
    withToast: false,
  },
  {
    name: "reference-drawer",
    root: THE_DRAWER,
    expects: ["Close"],
    withToast: false,
  },
  {
    name: "retire-dialog",
    root: A_DIALOG,
    expects: ["Cancel", "Retire category"],
    withToast: false,
  },
  {
    name: "retire-dialog-with-toast",
    root: A_DIALOG,
    expects: ["Cancel", "Retire category"],
    withToast: true,
  },
  {
    name: "chat",
    root: THE_DOCK,
    expects: ["New chat", "Close", "Send", "Message Claude"],
    withToast: false,
  },
  {
    name: "chat-with-toast",
    root: THE_DOCK,
    expects: ["New chat", "Close", "Send", "Message Claude"],
    withToast: true,
  },
  {
    name: "edit-proposal",
    root: THE_DOCK,
    expects: ["New chat", "Close", "Discard", "Approve and write", "Send", "Message Claude"],
    withToast: false,
  },
  {
    name: "edit-proposal-with-toast",
    root: THE_DOCK,
    expects: ["New chat", "Close", "Discard", "Approve and write", "Send", "Message Claude"],
    withToast: true,
  },
  {
    // The toasts' row at the cap it may take, which is the least height the dock is ever given.
    name: "edit-proposal-under-a-full-toast-lane",
    root: THE_DOCK,
    expects: ["New chat", "Close", "Discard", "Approve and write", "Send", "Message Claude"],
    withToast: true,
  },
  {
    name: "create-proposal",
    root: THE_DOCK,
    expects: ["New chat", "Close", "Discard", "Approve and write", "Send"],
    withToast: false,
  },
  {
    name: "hero-proposal",
    root: THE_DOCK,
    expects: ["New chat", "Close", "None of these", "Use this one", "Send"],
    withToast: false,
  },
  // The three below are the screens the owner only ever sees because something already went wrong,
  // which is the worst moment for the control that answers it to be somewhere a mouse cannot go.
  // Each names its trouble in a block of prose carrying no control of its own, so what is measured
  // is the wall or the stage still working at the height that block has left it.
  {
    name: "home-with-files-it-cannot-open",
    root: THE_SHELL,
    expects: THE_WALL,
    withToast: false,
  },
  {
    name: "home-with-a-shadowed-file",
    root: THE_SHELL,
    expects: THE_WALL,
    withToast: false,
  },
  {
    name: "category-excel-is-holding",
    root: THE_STAGE,
    expects: THE_CATEGORY,
    withToast: false,
  },
];
