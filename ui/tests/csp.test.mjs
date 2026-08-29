// Unit cover for the one place the console's CSP is built.
//
// These tests are cheap and they are NOT sufficient: the whole point of
// `scripts/assert-hydratable.mjs` is that the header string here is byte-identical in the working
// case and in the broken one, so a string assertion cannot see whether the page hydrates. What
// these do cover is the parts that ARE decidable from the string: the directives that must exist,
// the three-state framing read, and the fact that no directive is ever emitted empty.

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  UnhydratableCspError,
  WildcardOriginError,
  assertHydratableCsp,
  contentSecurityPolicy,
  frameAncestors,
  frameOptions,
  generateNonce,
} from "../lib/csp.mjs";

/** Split a policy into a directive -> value map. */
function directives(policy) {
  return new Map(
    policy
      .split(";")
      .map((piece) => piece.trim())
      .filter(Boolean)
      .map((piece) => {
        const [name, ...value] = piece.split(/\s+/);
        return [name, value.join(" ")];
      }),
  );
}

/** The environment a `next build` / `next start` deployment runs under. */
const PROD = { NODE_ENV: "production" };

test("the policy carries every directive the fleet standard requires", () => {
  const parsed = directives(contentSecurityPolicy({}, "abc123"));
  for (const name of [
    "default-src",
    "base-uri",
    "form-action",
    "object-src",
    "script-src",
    "style-src",
    "connect-src",
    "frame-ancestors",
  ]) {
    assert.ok(parsed.has(name), `missing ${name}`);
  }
  assert.equal(parsed.get("object-src"), "'none'");
  assert.equal(parsed.get("base-uri"), "'self'");
});

test("no directive is ever emitted empty, in any framing state", () => {
  for (const env of [{}, { NEXT_PUBLIC_FRAME_ANCESTORS: "" }, { NEXT_PUBLIC_FRAME_ANCESTORS: "  " }]) {
    for (const [name, value] of directives(contentSecurityPolicy(env, "n"))) {
      // An empty directive is a CSP parse error: the browser discards it, taking the restriction
      // with it, so the strictest-looking configuration would end up the least restrictive.
      assert.ok(value, `${name} is empty for env ${JSON.stringify(env)}`);
    }
  }
});

test("script-src takes the nonce and 'strict-dynamic' only when a nonce is supplied", () => {
  assert.equal(
    directives(contentSecurityPolicy(PROD, "abc123")).get("script-src"),
    "'self' 'nonce-abc123' 'strict-dynamic'",
  );
  assert.equal(directives(contentSecurityPolicy(PROD)).get("script-src"), "'self'");
});

test("the dev server gets eval and a websocket, and a production build never does", () => {
  // `npm run dev` compiles with `eval` and talks to Turbopack's HMR endpoint over a websocket.
  // Without these two relaxations the dev-served console renders completely and never hydrates,
  // which is exactly the failure `org-metadata/docs/demos/demo-inventory.md` records. The
  // relaxations must therefore EXIST in development and must NEVER exist in a production build,
  // so both halves are pinned here: dropping either branch turns one of these assertions red.
  const dev = directives(contentSecurityPolicy({ NODE_ENV: "development" }, "abc123"));
  assert.match(dev.get("script-src"), /'unsafe-eval'/);
  assert.match(dev.get("connect-src"), /\bws: wss:/);

  const prod = contentSecurityPolicy(PROD, "abc123");
  assert.doesNotMatch(prod, /unsafe-eval/);
  assert.doesNotMatch(prod, /ws:/);
  assert.doesNotMatch(prod, /wss:/);
});

test("the production policy is byte-identical to the one that shipped before the dev branch", () => {
  // The dev branch is only safe if it is invisible to a deployment. This pins the whole
  // production string, so a relaxation leaking out of the `isDev` guard cannot pass review.
  assert.equal(
    contentSecurityPolicy(PROD, "abc123"),
    "default-src 'self'; base-uri 'self'; form-action 'self'; object-src 'none'; " +
      "script-src 'self' 'nonce-abc123' 'strict-dynamic'; style-src 'self' 'unsafe-inline'; " +
      "img-src 'self' data:; font-src 'self' data:; connect-src 'self'; frame-ancestors 'self'",
  );
});

test("frame-ancestors is a three-state read matching the backend's", () => {
  assert.equal(frameAncestors({}), "'self'");
  assert.equal(frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: "" }), "'none'");
  assert.equal(frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: "   " }), "'none'");
  assert.equal(
    frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: " https://a.example  https://b.example " }),
    "https://a.example https://b.example",
  );
});

test("X-Frame-Options is sent only for the two states it can express", () => {
  assert.equal(frameOptions("'self'"), "SAMEORIGIN");
  assert.equal(frameOptions("'none'"), "DENY");
  assert.equal(frameOptions("https://parent.example"), "");
});

test("connect-src widens to the API origin only, never the whole API URL", () => {
  const parsed = directives(
    contentSecurityPolicy(
      { ...PROD, NEXT_PUBLIC_API_BASE: "https://api.example:8443/v1/briefings" },
      "n",
    ),
  );
  assert.equal(parsed.get("connect-src"), "'self' https://api.example:8443");
});

test("a rooted relative API base remains covered by same-origin", () => {
  const parsed = directives(
    contentSecurityPolicy({ ...PROD, NEXT_PUBLIC_API_BASE: "/apps/doc3/api" }, "n"),
  );
  assert.equal(parsed.get("connect-src"), "'self'");
});

test("an API base that is neither absolute nor rooted is refused", () => {
  assert.throws(
    () => contentSecurityPolicy({ NEXT_PUBLIC_API_BASE: "apps/doc3/api" }, "n"),
    /absolute or rooted relative URL/,
  );
});

test("every nonce is fresh and base64", () => {
  const nonces = new Set(Array.from({ length: 50 }, () => generateNonce()));
  assert.equal(nonces.size, 50);
  for (const nonce of nonces) assert.match(nonce, /^[A-Za-z0-9+/]+={0,2}$/);
});

test("a layout without force-dynamic is refused, because its HTML cannot carry the nonce", () => {
  assert.throws(
    () => assertHydratableCsp("export default function RootLayout() { return null; }"),
    UnhydratableCspError,
  );
  assert.doesNotThrow(() => assertHydratableCsp('export const dynamic = "force-dynamic";'));
});

test("a wildcard framing allowlist refuses, in bare and partial form", () => {
  // The FOURTH state. The backend refuses a wildcard; the console emits the header a browser
  // honours for the DOCUMENT, so a console that accepted `*` while the API refused it would be
  // the permissive half that governs. `https://*.example` is no better than the bare form: it
  // trusts every subdomain, including one an attacker managed to take.
  for (const value of ["*", "'self' https://*.parent.example"]) {
    assert.throws(
      () => frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: value }),
      /wildcard/,
      `frameAncestors accepted ${value}`,
    );
    assert.throws(() => contentSecurityPolicy({ NEXT_PUBLIC_FRAME_ANCESTORS: value }, "n"), /wildcard/);
  }
});

test("the wildcard refusal leaves the other three framing states alone", () => {
  assert.equal(frameAncestors({}), "'self'");
  assert.equal(frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: "" }), "'none'");
  assert.equal(frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: "'none'" }), "'none'");
  assert.equal(
    frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: " https://a.example  https://b.example " }),
    "https://a.example https://b.example",
  );
});

test("the literal null is refused, though it carries no asterisk", () => {
  // The refusal tested `token.includes("*")`, which catches every wildcard that is SPELLED as one
  // and cannot see this one. A sandboxed iframe presents a null origin, so `frame-ancestors null`
  // admits exactly the framing the directive exists to refuse, from a document whose own origin
  // the browser has already thrown away. It is a wildcard by behaviour rather than by spelling,
  // so it needs naming rather than deriving.
  for (const value of ["null", "https://parent.example null", "null https://parent.example"]) {
    assert.throws(
      () => frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: value }),
      WildcardOriginError,
      `frameAncestors accepted ${JSON.stringify(value)}`,
    );
    assert.throws(
      () => contentSecurityPolicy({ NEXT_PUBLIC_FRAME_ANCESTORS: value }, "n"),
      WildcardOriginError,
      `contentSecurityPolicy emitted ${JSON.stringify(value)}`,
    );
  }
});

test("every exact wildcard token is refused, asterisk or not", () => {
  // `*`, `'*'` and `*.*` already refuse under the asterisk rule. They are pinned against the
  // named set as well, so the two halves cannot drift apart and removing either one goes red.
  for (const value of ["*", "'*'", "*.*", "null"]) {
    assert.throws(
      () => frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: value }),
      WildcardOriginError,
      `frameAncestors accepted ${JSON.stringify(value)}`,
    );
  }
});

test("refusing the tokens does not refuse an origin that merely contains one", () => {
  // The refusal is exact-token, not substring. A refusal that also refuses valid input is an
  // outage rather than a control, and `https://nullify.example` is a perfectly good origin.
  assert.equal(
    frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: "https://nullify.example https://a.example" }),
    "https://nullify.example https://a.example",
  );
  assert.equal(frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: "https://null.example" }), "https://null.example");
});
