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
  | "category-excel-is-holding"
  | "unresolved-view"
  | "category-with-a-playable-entry"
  | "player-overlay"
  | "player-with-pending-save"
  | "closed-player-with-pending-save";

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
/**
 * The metadata providers' links, which the sidebar foot carries on every screen the shell holds.
 *
 * They are a licence obligation rather than a convenience, so a foot pushed below the fold is not a
 * cosmetic loss — and the foot is exactly where the stacked shell at the breakpoint would push it.
 */
const THE_ATTRIBUTION = ["TMDB", "thetvdb.com"];
/** Every control the cards wall promises, whatever else the library made it print underneath. */
const THE_WALL = [
  "Watch List",
  "Find a category",
  "Search categories",
  "New category",
  "Ask Claude",
  ...THE_ATTRIBUTION,
];
/** Every control an open category promises, whatever else the stage had to make room for. */
const THE_CATEGORY = [
  "All categories",
  "Retire category",
  `Search entries in ${A_CATEGORY}`,
  "Add entry",
  "Sheet notes",
  "Delete entry",
];
/**
 * Every control the review queue promises: the nav entry that reaches it, and one row's two decisions.
 *
 * Both decisions are measured per row rather than once, because the note above them is free text of
 * whatever length the resolver wrote and it is the row's own controls it would push down.
 */
const THE_UNRESOLVED_VIEW = ["Needs review", "Confirm", "Retry resolution", ...THE_ATTRIBUTION];
const THE_SHELL = ".shell";
const THE_STAGE = ".stage";
const A_DIALOG = ".dialog";
const THE_DRAWER = ".drawer";
const THE_DOCK = ".chat-dock";

export const SURFACES: readonly SurfaceSpec[] = [
  {
    name: "player-with-pending-save",
    root: ".player",
    expects: ["Close player", "Choose a playback item", "Video for The Long Way Round, Part 1"],
    withToast: true,
  },
  {
    name: "closed-player-with-pending-save",
    root: ".toasts",
    expects: ["Retry save", "Dismiss"],
    withToast: true,
  },
  {
    name: "category-with-a-playable-entry",
    root: THE_STAGE,
    expects: [...THE_CATEGORY, "Play The Long Way Round, Part 1"],
    withToast: false,
  },
  {
    name: "player-overlay",
    root: ".player",
    expects: ["Close player", "Choose a playback item", "Video for The Long Way Round, Part 1"],
    withToast: false,
  },
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
  {
    // The shell rather than the stage: the nav entry that reaches this screen is in the sidebar, and a
    // queue nothing can navigate to is a queue nobody works down.
    name: "unresolved-view",
    root: THE_SHELL,
    expects: THE_UNRESOLVED_VIEW,
    withToast: false,
  },
];
