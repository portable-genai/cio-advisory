/**
 * A stack of stages where only the one in focus is open.
 *
 * The problem it solves: a console that shows its evidence honestly gets tall. This one
 * shows the client, then their book, then the arithmetic against the model portfolio, then
 * the briefing — and by the time the briefing arrives the thing a reader came for is a
 * screen and a half down. Embedded in `journey-portal` it is worse, because the host gives
 * each app an iframe shorter than a full page.
 *
 * The move is to collapse what is ABOVE rather than scroll to what is below. Both put the
 * active stage in view; only one of them is stable. `scrollIntoView` on a page that is still
 * growing lands wherever the layout happened to be at the moment it fired, and it takes the
 * scroll position away from the reader, who then cannot tell whether they moved or the page
 * did. Collapsing above keeps the page pinned at the top and lets the active stage rise into
 * view on its own.
 *
 * Three rules the implementation exists to hold, each of which is a way this pattern is
 * usually got wrong:
 *
 * **A collapsed stage keeps its numbers.** The summary line carries the figures, so a stage
 * that closes still asserts what it found. Collapsing to a bare title would delete the
 * evidence the panel was added to show, which is worse than not collapsing at all. Today
 * the portfolio panel is UNMOUNTED when the briefing arrives, which is that failure in its
 * strongest form: the evidence does not just close, it leaves.
 *
 * **The reader outranks the state machine.** Once someone opens or closes a stage by hand,
 * that stage stops being driven automatically for the rest of the session. A panel that
 * reopens or slams shut under a reader who just touched it reads as broken.
 *
 * **Print shows everything.** A collapsed briefing that prints collapsed is a broken
 * deliverable, so `onbeforeprint` opens every stage.
 *
 * The provenance banner is deliberately NOT part of this: it lives in `app/layout.tsx`
 * outside `children`, so nothing here can collapse, push, or hide it. That is structural
 * rather than a convention, because a banner that scrolled off under an auto-collapse is a
 * defect this fleet has already shipped once.
 *
 * Native `<details>`/`<summary>` carries the keyboard and screen-reader behaviour, and the
 * open state survives with no JavaScript at all.
 */

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { activeStage, isDriven, isReaderToggle, withTakeover } from "@/lib/stages.mjs";

// Re-exported so a page imports the stack and its rule from one place; the rule itself
// lives in lib/stages.mjs where the gate can test it without a renderer.
export { activeStage };

//: Shared empty set so a Stage rendered without `taken` does not allocate one per render.
const EMPTY: ReadonlySet<string> = new Set<string>();

export interface StageProps {
  /** Stable id. Used to remember that a reader has taken this stage over. */
  id: string;
  /** Always visible. Put the stage's headline FIGURES here, not just its name. */
  summary: React.ReactNode;
  /** True when this is the stage the reader should be looking at now. */
  active: boolean;
  /** Called on every manual toggle so the stack can stop driving this stage. */
  onTakeOver?: (id: string) => void;
  /** The stages a reader has toggled. A stage in this set is no longer driven. */
  taken?: ReadonlySet<string>;
  children: React.ReactNode;
}

export function Stage({ id, summary, active, onTakeOver, taken, children }: StageProps) {
  const ref = useRef<HTMLDetailsElement>(null);
  // The last openness this component wrote. <details> fires `toggle` for a programmatic
  // write exactly as it does for a click, so without this the stack reads its own writes as
  // reader intent, marks every stage taken the moment it first opens one, and then never
  // collapses anything again. See isReaderToggle in lib/stages.mjs.
  const wrote = useRef<boolean | null>(null);

  // `active` drives the element directly rather than through React state: <details> owns its
  // own openness natively, and mirroring it into state means two sources of truth that
  // disagree the moment a reader clicks. Once `taken`, nothing here writes to it again.
  useEffect(() => {
    const el = ref.current;
    if (el && isDriven(id, taken ?? EMPTY)) {
      wrote.current = active;
      el.open = active;
    }
  }, [active, taken, id]);

  // A print must never be a screenshot of what happened to be collapsed. Opening every
  // stage on `beforeprint` is the only point at which the reader's choices are overridden,
  // and it is not a state change: the DOM is restored on `afterprint`.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let wasOpen = el.open;
    const open = () => {
      wasOpen = el.open;
      el.open = true;
    };
    const restore = () => {
      el.open = wasOpen;
    };
    window.addEventListener("beforeprint", open);
    window.addEventListener("afterprint", restore);
    return () => {
      window.removeEventListener("beforeprint", open);
      window.removeEventListener("afterprint", restore);
    };
  }, []);

  return (
    <details
      ref={ref}
      data-stage={id}
      className="group rounded-xl border border-ink-200 bg-white shadow-panel"
      onToggle={(event) => {
        // Only THIS element's toggles, and only ones the stack did not cause. The target
        // check matters because the panels inside a stage use <details> of their own for
        // their evidence drill-downs, and React delivers those to this handler too;
        // without it, opening a drill-down would freeze the stage that contains it.
        if (event.target !== ref.current || !ref.current) return;
        if (isReaderToggle(ref.current.open, wrote.current)) onTakeOver?.(id);
      }}
    >
      <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-3 text-sm text-ink-700 [&::-webkit-details-marker]:hidden">
        <span
          aria-hidden="true"
          className="text-ink-400 transition-transform group-open:rotate-90"
        >
          &#9656;
        </span>
        <span className="min-w-0 flex-1">{summary}</span>
      </summary>
      <div className="border-t border-ink-100 px-4 py-4">{children}</div>
    </details>
  );
}

/**
 * Remembers which stages a reader has taken over.
 *
 * Deliberately not a reducer over the stage list: the set only ever grows, and a stage that
 * has been taken over stays taken over even if it unmounts and comes back, because the
 * reader's intent did not expire when the DOM did.
 */
export function useStageTakeover() {
  const [taken, setTaken] = useState<Set<string>>(() => new Set());
  const onTakeOver = useCallback((id: string) => {
    setTaken((prev) => withTakeover(prev, id) as Set<string>);
  }, []);
  return { taken, onTakeOver };
}

