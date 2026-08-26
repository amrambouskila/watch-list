import type { Page } from "@playwright/test";

/**
 * Every control a pointer can be aimed at, disabled ones included.
 *
 * Wider than the focus trap's list on purpose: a disabled button that renders off-screen is still
 * off-screen the moment it enables, and that is exactly how the Approve button shipped.
 */
const CONTROL_SELECTOR = 'button, a[href], input, textarea, select, [tabindex]:not([tabindex="-1"])';
/** Rects land on subpixels; half a pixel over the edge is rounding, not a control off the screen. */
const EDGE_TOLERANCE_PX = 0.5;
/**
 * Hit testing snaps to whole pixels and `getBoundingClientRect` does not, so the browser answers
 * with elements up to a pixel outside the box it reports for them. Asking whether a box holds a
 * point has to allow that much, or every boundary between two boxes reads as one leaking.
 */
const HIT_TOLERANCE_PX = 1;
/**
 * Points per axis across each box of a control, taken at the centre of every cell of the grid and
 * never on its edges, so a border or an antialiased corner is not what decides the reading.
 *
 * Five puts the outermost points a tenth of the way in, which is the smallest bite out of a
 * control's width or height this can see. It also sets the floor below: the corners of a round
 * control fall outside the control's own shape, and a circle answers 21 of these 25 points, so the
 * floor has to sit under 0.84 — while still failing a control a quarter eaten.
 */
const SAMPLES_PER_AXIS = 5;
/**
 * How far inside its own edge a control's perimeter is walked.
 *
 * The grid above is blind to anything thinner than a fifth of a control, which is the gap between
 * two of its rows, and blind to the outermost tenth altogether. Occlusion does not land there at
 * random: a toast, a pane, or a table that has stopped scrolling arrives from an edge, so the edges
 * are where more points buy something and the interior is where they would not. Two pixels is
 * inside the smallest corner radius the app draws and outside the antialiasing along a border.
 */
const PERIMETER_INSET_PX = 2;
/**
 * Points along each side of that perimeter, so a twentieth of a side separates two of them.
 *
 * They only ever say whether something foreign is there, and never count towards the fraction
 * below: a round control has no shape at the corners of its own box, so counting the points that
 * miss it would fail every circle in the app.
 */
const PERIMETER_SAMPLES_PER_SIDE = 21;
/** How much of a control has to answer a click before the guard calls it reachable. */
export const MIN_CLICKABLE_FRACTION = 0.75;
/**
 * How much of what the app meant to show of a control has to actually be there, on each axis,
 * before it is still a control rather than a sliver of one.
 *
 * Half. A pane that shortens its content on purpose sets what was meant rather than spending this
 * — see `trimsOnPurpose` — so only a pane with no business cutting the control can fail it.
 */
export const MIN_VISIBLE_FRACTION = 0.5;

export interface ControlReach {
  readonly name: string;
  /** The control's own box after every pane above it has clipped it: what is really on screen. */
  readonly width: number;
  readonly height: number;
  readonly onScreen: boolean;
  /** The least share of an axis of the control the app meant to show that a pane has not eaten. */
  readonly visibleFraction: number;
  /** The share of that visible area where a click reaches the control and not something else. */
  readonly clickableFraction: number;
  /** One line per thing painted over the control, or spilled under it out of a box of its own. */
  readonly obstructions: readonly string[];
}

/**
 * What a person would find at each control of a surface: how much of it is on screen, and how much
 * of that answers a click.
 *
 * Each control is first scrolled to the middle of every scroller a person can actually work, which
 * also clears whatever sticky edge such a pane holds. Never `Element.scrollIntoView`, which also
 * scrolls `overflow: hidden` boxes: those reveal nothing to a wheel or a scrollbar, so letting the
 * guard scroll one would report a sliced-off button as reachable.
 *
 * A control is then judged on the area its panes have left visible rather than on its whole border
 * box, because a box deliberately ellipsised by an ancestor is perfectly usable at the width that
 * is on screen. Every cell of that area is sampled, and its perimeter walked, and a point counts
 * against the control both when something foreign is painted over it and when something foreign has
 * escaped a box of its own to sit under it — the second is how a table that has stopped scrolling
 * runs on beneath the buttons below it. As much of the control as the app promised has to be there
 * as well, or one an unrelated pane has sliced to a sliver passes for being a clickable sliver.
 */
export function measureControls(page: Page, root: string): Promise<ControlReach[]> {
  return page.evaluate(
    ({ rootSelector, controlSelector, edgeTolerance, hitTolerance, perAxis, inset, perSide }) => {
      interface Edges {
        readonly top: number;
        readonly left: number;
        readonly bottom: number;
        readonly right: number;
      }

      /** One line the control occupies: what is left of it on screen, and what was meant to be. */
      interface Shown {
        readonly box: Edges;
        readonly meant: Edges;
      }

      const scrolls = (value: string): boolean => value === "auto" || value === "scroll";

      const placed = (position: string): boolean => position === "fixed" || position === "absolute";

      const holds = (edges: Edges, x: number, y: number): boolean =>
        x >= edges.left - hitTolerance &&
        x <= edges.right + hitTolerance &&
        y >= edges.top - hitTolerance &&
        y <= edges.bottom + hitTolerance;

      const intersect = (one: Edges, other: Edges): Edges => ({
        top: Math.max(one.top, other.top),
        left: Math.max(one.left, other.left),
        bottom: Math.min(one.bottom, other.bottom),
        right: Math.min(one.right, other.right),
      });

      const empty = (edges: Edges): boolean => edges.right <= edges.left || edges.bottom <= edges.top;

      const screen: Edges = { top: 0, left: 0, bottom: window.innerHeight, right: window.innerWidth };

      /** Whether this box is the one a fixed descendant is laid out against, rather than the window. */
      const anchorsFixed = (style: CSSStyleDeclaration): boolean =>
        style.transform !== "none" ||
        style.perspective !== "none" ||
        style.filter !== "none" ||
        style.backdropFilter !== "none" ||
        style.contain !== "none";

      /**
       * Whether this pane shortens what it holds on purpose, which it says by asking for an ellipsis.
       *
       * The source chips over a proposal are cut to a fifth of their URL that way and are meant to
       * be: the app promises the link, not the address. Such a pane does not excuse the trim, it
       * says what the full size of the control was meant to be, so a pane further out that eats what
       * is left still answers for it. It is a promise about width alone — an ellipsis never put a
       * line back — so nothing a trimming pane does vertically is spared.
       */
      const trimsOnPurpose = (style: CSSStyleDeclaration): boolean => style.textOverflow !== "clip";

      /** Where a pane actually clips: its padding box, which sits inside whatever border it draws. */
      const paddingBox = (node: Element): Edges => {
        const rect = node.getBoundingClientRect();
        const style = getComputedStyle(node);
        return {
          top: rect.top + parseFloat(style.borderTopWidth),
          left: rect.left + parseFloat(style.borderLeftWidth),
          bottom: rect.bottom - parseFloat(style.borderBottomWidth),
          right: rect.right - parseFloat(style.borderRightWidth),
        };
      };

      /**
       * The panes whose clipping and scrolling actually reach the control, innermost first.
       *
       * A fixed or absolutely positioned box is laid out against its containing block rather than
       * against its parent, so panes it is merely nested inside neither clip it nor scroll it: the
       * drawer sits inside the stage in the markup and over the whole window on screen.
       */
      const panesOver = (control: Element): Element[] => {
        const panes: Element[] = [];
        let position = getComputedStyle(control).position;
        for (let node = control.parentElement; node !== null; node = node.parentElement) {
          const style = getComputedStyle(node);
          const anchors =
            position === "fixed" ? anchorsFixed(style) : anchorsFixed(style) || style.position !== "static";
          if (placed(position) && !anchors) continue;
          panes.push(node);
          position = style.position;
        }
        return panes;
      };

      const bringIntoView = (control: Element, panes: readonly Element[]): void => {
        for (const node of panes) {
          const style = getComputedStyle(node);
          if (scrolls(style.overflowY)) {
            const pane = paddingBox(node);
            const box = control.getBoundingClientRect();
            node.scrollTop += (box.top + box.bottom) / 2 - (pane.top + pane.bottom) / 2;
          }
          if (scrolls(style.overflowX)) {
            const pane = paddingBox(node);
            const box = control.getBoundingClientRect();
            node.scrollLeft += (box.left + box.right) / 2 - (pane.left + pane.right) / 2;
          }
        }
        const box = control.getBoundingClientRect();
        const down = box.bottom > screen.bottom ? box.bottom - screen.bottom : Math.min(0, box.top);
        const across = box.right > screen.right ? box.right - screen.right : Math.min(0, box.left);
        window.scrollBy(across, down);
      };

      /**
       * One reading per line the control occupies, clipped by every pane that hides its overflow.
       *
       * Per line rather than one bounding box, because the bounding box of a link wrapped over three
       * lines also spans the empty end of the last one, which belongs to the paragraph behind it.
       *
       * `meant` is the same line under the width a trimming pane shortened it to and nothing else,
       * which is the size the floor below measures against: the app promised that much of the
       * control, so that much is what an unrelated pane can be caught eating.
       */
      const shownBoxes = (control: Element, panes: readonly Element[]): Shown[] => {
        const clips: Edges[] = [];
        const promised: Edges[] = [];
        for (const node of panes) {
          const style = getComputedStyle(node);
          const wide = style.overflowX === "visible";
          const tall = style.overflowY === "visible";
          if (wide && tall) continue;
          const box = paddingBox(node);
          const edges: Edges = {
            top: tall ? -Infinity : box.top,
            left: wide ? -Infinity : box.left,
            bottom: tall ? Infinity : box.bottom,
            right: wide ? Infinity : box.right,
          };
          clips.push(edges);
          if (trimsOnPurpose(style)) {
            promised.push({ top: -Infinity, bottom: Infinity, left: edges.left, right: edges.right });
          }
        }
        return [...control.getClientRects()]
          .map((rect) => ({
            box: clips.reduce<Edges>(intersect, rect),
            meant: promised.reduce<Edges>(intersect, rect),
          }))
          .filter((shown) => !empty(shown.box));
      };

      /** The share of one promised axis still there; a control promised no extent has lost none. */
      const survived = (shown: number, meant: number): number => (meant <= 0 ? 1 : Math.max(0, shown) / meant);

      /**
       * The ring of points just inside one box's own edge, corners included.
       *
       * The inset is clamped, so a control thinner than two of them is walked up its own middle
       * rather than along a side that is no longer there.
       */
      const perimeterOf = (area: Edges): readonly { readonly x: number; readonly y: number }[] => {
        const width = area.right - area.left;
        const height = area.bottom - area.top;
        const inX = Math.min(inset, width / 2);
        const inY = Math.min(inset, height / 2);
        const points: { x: number; y: number }[] = [];
        for (let step = 0; step < perSide; step += 1) {
          const along = step / (perSide - 1);
          const x = area.left + inX + (width - 2 * inX) * along;
          const y = area.top + inY + (height - 2 * inY) * along;
          points.push({ x, y: area.top + inY });
          points.push({ x, y: area.bottom - inY });
          points.push({ x: area.left + inX, y });
          points.push({ x: area.right - inX, y });
        }
        return points;
      };

      const describe = (element: Element): string => {
        const classes = element.getAttribute("class");
        return element.tagName.toLowerCase() + (classes === null ? "" : `.${classes.trim().split(/\s+/).join(".")}`);
      };

      const nameOf = (element: Element): string => {
        const labelled = element.getAttribute("aria-label") ?? element.getAttribute("placeholder");
        const text = (element.textContent ?? "").replace(/\s+/g, " ").trim();
        if (labelled !== null) return labelled;
        return text === "" ? describe(element) : text;
      };

      const container = document.querySelector(rootSelector);
      if (container === null) return [];

      return [...container.querySelectorAll(controlSelector)].map((control) => {
        // Which panes reach the control is structural, so scrolling them cannot change the list.
        const panes = panesOver(control);
        bringIntoView(control, panes);

        const boxes = shownBoxes(control, panes);
        const onScreen =
          boxes.length > 0 &&
          boxes.every(
            (shown) =>
              shown.box.top >= screen.top - edgeTolerance &&
              shown.box.left >= screen.left - edgeTolerance &&
              shown.box.bottom <= screen.bottom + edgeTolerance &&
              shown.box.right <= screen.right + edgeTolerance,
          );

        /** Nothing moves while one control is sampled, so each element is read once. */
        const boxOf = new Map<Element, Edges>();
        const edgesOf = (element: Element): Edges => {
          const known = boxOf.get(element);
          if (known !== undefined) return known;
          const measured: Edges = element.getBoundingClientRect();
          boxOf.set(element, measured);
          return measured;
        };
        const outOfFlow = new Map<Element, boolean>();
        const isPlaced = (element: Element): boolean => {
          const known = outOfFlow.get(element);
          if (known !== undefined) return known;
          const measured = placed(getComputedStyle(element).position);
          outOfFlow.set(element, measured);
          return measured;
        };

        /**
         * The box a foreign element's content ran out of before reaching the control's own tree.
         *
         * A box that was placed rather than flowed is meant to sit outside its parent, so the walk
         * stops there: only content that overflowed the box it was laid out in counts as escaped.
         */
        const escapedFrom = (element: Element, x: number, y: number): Element | null => {
          for (let node: Element | null = element; node !== null; node = node.parentElement) {
            if (isPlaced(node)) return null;
            const parent = node.parentElement;
            if (parent === null || parent.contains(control)) return null;
            if (!holds(edgesOf(parent), x, y)) return parent;
          }
          return null;
        };

        const obstructions = new Set<string>();
        let sampled = 0;
        let clickable = 0;

        /** One reading of the stack at one point; only the grid's points say what answers a click. */
        const readAt = (x: number, y: number, counts: boolean): void => {
          const stack = document.elementsFromPoint(x, y);
          const own = stack.findIndex((element) => control.contains(element));
          // With the control nowhere in the stack, only what a click would hit sits above it.
          const above = own === -1 ? 1 : own;
          if (counts) {
            sampled += 1;
            if (own === 0) clickable += 1;
          }
          stack.forEach((element, depth) => {
            if (control.contains(element) || element.contains(control)) return;
            if (depth < above) {
              obstructions.add(`${describe(element)} covers it`);
              return;
            }
            const escaped = escapedFrom(element, x, y);
            if (escaped !== null) obstructions.add(`${describe(escaped)} has spilled out from under it`);
          });
        };

        let visibleFraction = boxes.length === 0 ? 0 : 1;

        for (const shown of boxes) {
          visibleFraction = Math.min(
            visibleFraction,
            survived(shown.box.right - shown.box.left, shown.meant.right - shown.meant.left),
            survived(shown.box.bottom - shown.box.top, shown.meant.bottom - shown.meant.top),
          );

          const area = intersect(shown.box, screen);
          if (empty(area)) continue;
          for (let column = 0; column < perAxis; column += 1) {
            for (let row = 0; row < perAxis; row += 1) {
              const x = area.left + ((area.right - area.left) * (column + 0.5)) / perAxis;
              const y = area.top + ((area.bottom - area.top) * (row + 0.5)) / perAxis;
              readAt(x, y, true);
            }
          }
          for (const point of perimeterOf(area)) readAt(point.x, point.y, false);
        }

        const bounds = boxes.reduce(
          (one, shown) => ({
            top: Math.min(one.top, shown.box.top),
            left: Math.min(one.left, shown.box.left),
            bottom: Math.max(one.bottom, shown.box.bottom),
            right: Math.max(one.right, shown.box.right),
          }),
          { top: Infinity, left: Infinity, bottom: -Infinity, right: -Infinity },
        );

        return {
          name: nameOf(control),
          width: boxes.length === 0 ? 0 : bounds.right - bounds.left,
          height: boxes.length === 0 ? 0 : bounds.bottom - bounds.top,
          onScreen,
          visibleFraction,
          clickableFraction: sampled === 0 ? 0 : clickable / sampled,
          obstructions: [...obstructions].sort(),
        };
      });
    },
    {
      rootSelector: root,
      controlSelector: CONTROL_SELECTOR,
      edgeTolerance: EDGE_TOLERANCE_PX,
      hitTolerance: HIT_TOLERANCE_PX,
      perAxis: SAMPLES_PER_AXIS,
      inset: PERIMETER_INSET_PX,
      perSide: PERIMETER_SAMPLES_PER_SIDE,
    },
  );
}
