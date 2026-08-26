import { applyProposal, sendChatMessage, setChatOpen } from "../../src/stores/chatSlice";
import { selectCategory, setNewCategoryOpen, setReferenceOpen, toggleRow } from "../../src/stores/uiSlice";
import type { ChatEvent } from "../../src/types/ChatEvent";
import type { Proposal } from "../../src/types/Proposal";
import { A_CATEGORY_ID } from "../../tests/support/aProposalBody";
import type { TestStore } from "../../tests/support/aTestStore";
import type { SurfaceName } from "../surfaces";
import { aCrowdedHeroProposal } from "./aCrowdedHeroProposal";
import { A_REFUSED_WRITE } from "./aFakeBackend";
import { aLibraryExcelIsHolding } from "./aLibraryExcelIsHolding";
import { aLibraryWithAShadowedFile } from "./aLibraryWithAShadowedFile";
import { aLibraryWithFilesItCannotOpen } from "./aLibraryWithFilesItCannotOpen";
import { aLongEditProposal } from "./aLongEditProposal";
import { aNewCategoryProposal } from "./aNewCategoryProposal";
import { FIRST_DATA_ROW } from "./aProbeCategory";
import type { ProbeLibrary } from "./aProbeLibrary";
import { fillTheToastLane } from "./fillTheToastLane";
import { holdAToastOnScreen } from "./holdAToastOnScreen";
import { untilPresent } from "./untilPresent";

const A_QUESTION = "Put the published run in order and add whatever the chronology is missing.";
const A_TURN_COST_USD = 0.2137;
const RETIRE_BUTTON = ".banner__retire";
const ADD_ENTRY_BUTTON = "Add entry";
const CARD = ".card";
const ROUTE_ENTRY = ".route__entry";
const ROW_DETAIL = ".detail";
const DIALOG = ".dialog";
const DRAWER = ".drawer";
const EYEBROW = ".eyebrow";
const COULD_NOT_BE_OPENED = "Could not be opened";
const HIDDEN_BY_ANOTHER_FILE = "Hidden by another file";
const LOCKED_BANNER = ".notice--locked";

/** How the guard puts one surface on screen, and the turn the fake backend streams to get it there. */
export interface Arrangement {
  readonly turn: readonly ChatEvent[];
  /**
   * The library the fake backend answers with, when the ordinary one is not the point.
   *
   * Only the surfaces about something being wrong with the library need it, and the app learns
   * about that at the same boundary it learns everything else: what the backend answered.
   */
  readonly library?: ProbeLibrary;
  readonly drive: (store: TestStore) => Promise<void>;
}

/** A turn that reads like a real one, and the shape that leaves the dock at its narrow width. */
function aTurnAnswering(): readonly ChatEvent[] {
  return [
    { type: "text", text: "Reading the published chronology now." },
    { type: "tool", name: "fetch_url", detail: "example.invalid/watch-orders", state: "done" },
    { type: "text", text: "That order disagrees with the sheet in three places. Here is what I would write." },
  ];
}

/** The same turn carrying a proposal, which is what widens the dock. */
function aTurnEndingIn(proposal: Proposal): readonly ChatEvent[] {
  return [...aTurnAnswering(), { type: "proposal", proposal }, { type: "done", total_cost_usd: A_TURN_COST_USD }];
}

async function askClaude(store: TestStore): Promise<void> {
  store.dispatch(setChatOpen(true));
  await store.dispatch(sendChatMessage(A_QUESTION));
}

function aChatArrangement(proposal: Proposal): Arrangement {
  return { turn: aTurnEndingIn(proposal), drive: askClaude };
}

/** The cards wall the app opens on, once the library it reads has arrived. */
async function showTheCardsWall(): Promise<void> {
  await untilPresent(CARD);
}

/**
 * The wall, plus the block the library's own trouble is named in, found by its heading.
 *
 * Waiting for the heading rather than only for a card is what makes each of these a surface of its
 * own: a probe served the ordinary library would time out here instead of measuring the plain wall
 * and passing on it.
 */
function alsoShowingTheBlockHeaded(heading: string): () => Promise<void> {
  return async () => {
    await showTheCardsWall();
    await untilPresent(EYEBROW, heading);
  };
}

/** The category as it reads while Excel holds its workbook: everything, under a banner saying so. */
async function openTheCategoryExcelIsHolding(store: TestStore): Promise<void> {
  await openTheCategory(store);
  await untilPresent(LOCKED_BANNER);
}

/** A category with one entry opened, so the row's own fields and its delete are on screen too. */
async function openTheCategory(store: TestStore): Promise<void> {
  store.dispatch(selectCategory(A_CATEGORY_ID));
  await untilPresent(ROUTE_ENTRY);
  store.dispatch(toggleRow(FIRST_DATA_ROW));
  await untilPresent(ROW_DETAIL);
}

/** The dialog opens from the banner and nowhere else, so the probe opens it from the banner. */
async function openTheRetireDialog(store: TestStore): Promise<void> {
  store.dispatch(selectCategory(A_CATEGORY_ID));
  (await untilPresent<HTMLButtonElement>(RETIRE_BUTTON)).click();
  await untilPresent(DIALOG);
}

/** Whether this dialog is open is the stage's own state, so only its button can open it. */
async function openTheAddEntryDialog(store: TestStore): Promise<void> {
  await openTheCategory(store);
  (await untilPresent<HTMLButtonElement>("button", ADD_ENTRY_BUTTON)).click();
  await untilPresent(DIALOG);
}

async function openTheNewCategoryDialog(store: TestStore): Promise<void> {
  store.dispatch(setNewCategoryOpen(true));
  await untilPresent(DIALOG);
}

async function openTheReferenceDrawer(store: TestStore): Promise<void> {
  store.dispatch(selectCategory(A_CATEGORY_ID));
  await untilPresent(ROUTE_ENTRY);
  store.dispatch(setReferenceOpen(true));
  await untilPresent(DRAWER);
}

/**
 * Approving against a workbook Excel is holding, which is the moment the app raises a toast from
 * inside the open dock — and so the moment a toast landing on the dock would cost the most.
 */
async function askClaudeAndFailToWrite(store: TestStore): Promise<void> {
  await askClaude(store);
  const proposal = store.getState().chat.pendingProposal;
  if (proposal === null) throw new Error("The turn ended with no proposal to approve.");
  await store.dispatch(applyProposal(proposal.id));
  holdAToastOnScreen(store, A_REFUSED_WRITE);
}

/** The same surface with a toast up, raised in the words the refusal above would have used. */
function alsoShowingAToast(arrangement: Arrangement): Arrangement {
  return {
    turn: arrangement.turn,
    drive: async (store) => {
      await arrangement.drive(store);
      holdAToastOnScreen(store, A_REFUSED_WRITE);
    },
  };
}

/**
 * The same surface with the toasts' row as full as it is ever allowed to get.
 *
 * One refusal per queued write is what a locked workbook really produces, and the row they fill is
 * height the app no longer has. This is the surface that says the dock still works at that height.
 */
function alsoUnderAFullToastLane(arrangement: Arrangement): Arrangement {
  return {
    turn: arrangement.turn,
    drive: async (store) => {
      await arrangement.drive(store);
      await fillTheToastLane(store, A_REFUSED_WRITE);
    },
  };
}

const HOME: Arrangement = { turn: [], drive: showTheCardsWall };
const CHAT: Arrangement = { turn: aTurnAnswering(), drive: askClaude };
const RETIRE_DIALOG: Arrangement = { turn: [], drive: openTheRetireDialog };
const AN_EDIT: Arrangement = aChatArrangement(aLongEditProposal());

export const ARRANGEMENTS: Readonly<Record<SurfaceName, Arrangement>> = {
  home: HOME,
  "home-with-toast": alsoShowingAToast(HOME),
  category: { turn: [], drive: openTheCategory },
  "add-entry-dialog": { turn: [], drive: openTheAddEntryDialog },
  "new-category-dialog": { turn: [], drive: openTheNewCategoryDialog },
  "reference-drawer": { turn: [], drive: openTheReferenceDrawer },
  "retire-dialog": RETIRE_DIALOG,
  "retire-dialog-with-toast": alsoShowingAToast(RETIRE_DIALOG),
  chat: CHAT,
  "chat-with-toast": alsoShowingAToast(CHAT),
  "edit-proposal": AN_EDIT,
  "edit-proposal-with-toast": { turn: AN_EDIT.turn, drive: askClaudeAndFailToWrite },
  "edit-proposal-under-a-full-toast-lane": alsoUnderAFullToastLane(AN_EDIT),
  "create-proposal": aChatArrangement(aNewCategoryProposal()),
  "hero-proposal": aChatArrangement(aCrowdedHeroProposal()),
  "home-with-files-it-cannot-open": {
    turn: [],
    library: aLibraryWithFilesItCannotOpen(),
    drive: alsoShowingTheBlockHeaded(COULD_NOT_BE_OPENED),
  },
  "home-with-a-shadowed-file": {
    turn: [],
    library: aLibraryWithAShadowedFile(),
    drive: alsoShowingTheBlockHeaded(HIDDEN_BY_ANOTHER_FILE),
  },
  "category-excel-is-holding": {
    turn: [],
    library: aLibraryExcelIsHolding(),
    drive: openTheCategoryExcelIsHolding,
  },
};
