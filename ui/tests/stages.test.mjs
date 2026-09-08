/**
 * The stage stack's rules, pinned against the ways this pattern is usually got wrong.
 *
 * These import `lib/stages.mjs` itself rather than mirroring it, so a rule that changes in
 * the component changes here too. What is checked is the DECISION — which stage is in
 * focus, and whether the stack still drives a stage — because that is the half that fails
 * silently. Whether the collapsed panel is legible is a browser question, and
 * `assert-hydratable` plus the walkthrough own it.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { activeStage, isDriven, isReaderToggle, withTakeover } from "../lib/stages.mjs";

// --------------------------------------------------------------------------- //
// activeStage: the newest content is the focus
// --------------------------------------------------------------------------- //
test("before anything is ready the first stage is the focus, not nothing", () => {
  assert.equal(
    activeStage([
      { id: "portfolio", ready: false },
      { id: "briefing", ready: false },
    ]),
    "portfolio",
  );
});

test("the last ready stage is the focus, so a new result takes focus from an old one", () => {
  const stages = [
    { id: "portfolio", ready: true },
    { id: "briefing", ready: true },
  ];
  assert.equal(activeStage(stages), "briefing");
});

test("a stage that is not ready never takes focus from one that is", () => {
  assert.equal(
    activeStage([
      { id: "portfolio", ready: true },
      { id: "briefing", ready: false },
    ]),
    "portfolio",
  );
});

test("readiness is read in display order, not by position in the ready set", () => {
  // A briefing arriving while the portfolio is still loading must not leave the console
  // focused on an empty portfolio stage.
  assert.equal(
    activeStage([
      { id: "portfolio", ready: false },
      { id: "briefing", ready: true },
    ]),
    "briefing",
  );
});

test("an empty stack asks for no stage rather than throwing", () => {
  assert.equal(activeStage([]), "");
});

// --------------------------------------------------------------------------- //
// isDriven / withTakeover: the reader outranks the state machine
// --------------------------------------------------------------------------- //
test("an untouched stage is driven by the stack", () => {
  assert.equal(isDriven("briefing", new Set()), true);
});

test("a stage the reader has toggled is never driven again", () => {
  const taken = withTakeover(new Set(), "portfolio");
  assert.equal(isDriven("portfolio", taken), false);
  // The rule is one-way: nothing in the module puts a stage back under automatic control,
  // which is what stops a panel slamming shut under a reader who just opened it.
  assert.equal(isDriven("portfolio", withTakeover(taken, "portfolio")), false);
});

test("taking over one stage leaves the others driven", () => {
  const taken = withTakeover(new Set(), "portfolio");
  assert.equal(isDriven("briefing", taken), true);
});

test("re-taking a stage returns the SAME set, so React does not re-render on every toggle", () => {
  const taken = withTakeover(new Set(), "portfolio");
  assert.equal(withTakeover(taken, "portfolio"), taken);
});

test("taking over a new stage returns a new set and keeps the old entries", () => {
  const first = withTakeover(new Set(), "portfolio");
  const second = withTakeover(first, "briefing");
  assert.notEqual(second, first);
  assert.deepEqual([...second].sort(), ["briefing", "portfolio"]);
});

// --------------------------------------------------------------------------- //
// isReaderToggle: the stack must not read its own writes as reader intent
// --------------------------------------------------------------------------- //
// This block exists because the first version of the stage stack shipped without it and
// did nothing at all: <details> fires `toggle` for a programmatic `el.open = x` just as it
// does for a click, so the stack marked each stage taken the instant it first opened one,
// and then never collapsed anything. The console looked exactly as it had before.
test("a toggle that matches what the stack wrote is the stack's own echo, not the reader", () => {
  assert.equal(isReaderToggle(true, true), false);
  assert.equal(isReaderToggle(false, false), false);
});

test("a toggle that disagrees with what the stack wrote is the reader", () => {
  // The stack opened it and it is now closed: somebody closed it.
  assert.equal(isReaderToggle(false, true), true);
  // The stack collapsed it and it is now open: somebody opened it.
  assert.equal(isReaderToggle(true, false), true);
});

test("a toggle before the stack has written anything is the reader", () => {
  // No write to attribute it to, so it can only have come from a hand on the mouse.
  assert.equal(isReaderToggle(true, null), true);
  assert.equal(isReaderToggle(false, null), true);
});

test("the open-collapse-open cycle a stack drives never registers as a takeover", () => {
  // Walk the real sequence: portfolio opens, briefing arrives and portfolio collapses.
  let taken = new Set();
  const drive = (open, expected) => {
    if (isReaderToggle(open, expected)) taken = withTakeover(taken, "portfolio");
  };
  drive(true, true); // stage opens under the stack
  drive(false, false); // stage collapses under the stack
  assert.equal(taken.size, 0);
  assert.equal(isDriven("portfolio", taken), true);
});
