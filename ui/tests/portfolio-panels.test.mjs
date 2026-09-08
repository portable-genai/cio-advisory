/**
 * The panels that make a recommendation mean something, pinned as pure functions.
 *
 * These assert the WORDING decisions the browser check found wrong the first time: a client
 * holding 35 percent of an asset class inside its band was being told they had "no position"
 * in it, because the panel keyed only on whether a gap object was present. Rendering is
 * checked in the browser by `assert-hydratable` and the walkthrough; what is checked here is
 * the logic that chose those words, which is the part that silently goes wrong.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

/** Mirrors CioViewsPanel's Implication: which sentence a theme earns. */
function implication(link) {
  const gap = link.addresses ?? link.exposure;
  if (!gap) return link.related_holdings.length > 0 ? "in-band" : "no-position";
  return link.addresses ? "closes" : "bears-on";
}

const gap = (over) => ({
  asset_class: "equity",
  current_weight: over ? 0.65 : 0.3,
  target_weight: 0.45,
  min_weight: 0.35,
  max_weight: 0.55,
  status: over ? "over" : "under",
  current_value: 1,
  total_value: 10,
  drift: over ? 0.2 : -0.15,
  value_gap: over ? -2 : 1.8,
});

test("an opportunity in an under-allocated class says it closes the gap", () => {
  assert.equal(
    implication({ addresses: gap(false), exposure: null, related_holdings: [] }),
    "closes",
  );
});

test("a threat says what it bears on", () => {
  assert.equal(
    implication({ addresses: null, exposure: gap(true), related_holdings: ["Fund"] }),
    "bears-on",
  );
});

test("a held, in-band class is not reported as no position", () => {
  // The defect the browser check caught: this used to render "No position and no shortfall"
  // for a client holding 35 percent of the class.
  assert.equal(
    implication({ addresses: null, exposure: null, related_holdings: ["IG Bond Fund"] }),
    "in-band",
  );
});

test("a class the client genuinely does not hold still says no position", () => {
  assert.equal(
    implication({ addresses: null, exposure: null, related_holdings: [] }),
    "no-position",
  );
});
