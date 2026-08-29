// The console's Content-Security-Policy, in one module so it is built once and read everywhere.
//
// Emitting it inline in `next.config.mjs` through the static `headers()` table allows exactly
// one directive: `frame-ancestors`. Nothing constrained where a script could
// come from, what a plugged-in `<base>` tag could re-point the relative URLs at, or whether an
// `<object>` could smuggle in a plugin document. The backend middleware in
// `src/cio_advisory/api/app.py` covers API responses only; the document a browser actually parses
// and executes is served by Next, so the document-layer policy has to be complete here.
//
// The policy now lives in this module, the nonce is minted per request in `proxy.ts`, and
// `next.config.mjs` no longer emits a `Content-Security-Policy` at all. Two layers both setting it
// would hand the browser two policies to INTERSECT, and the stricter one wins on every directive:
// a nonce-less policy from either layer can block Next's own inline hydration script.

/** Origin of the API base, when the console is deployed cross-origin from its service. */
function apiOrigin(env) {
  const raw = env.NEXT_PUBLIC_API_BASE || "";
  if (!raw) return "";
  if (raw.startsWith("/") && !raw.startsWith("//")) return "";
  try {
    return new URL(raw).origin;
  } catch {
    throw new Error(`NEXT_PUBLIC_API_BASE must be an absolute or rooted relative URL, got: ${raw}`);
  }
}

/**
 * Three-state read of `NEXT_PUBLIC_FRAME_ANCESTORS`; an emptied value REFUSES all framing.
 *
 * This mirrors `_frame_ancestors` in `src/cio_advisory/api/app.py` deliberately: the backend and
 * the console are two halves of one embedding posture, and an operator who sets one variable and
 * its console twin should not get two different answers. Unset keeps the shipped `'self'`. Set to
 * a value naming no origin would emit `frame-ancestors` with an EMPTY directive, which is a CSP
 * parse error: browsers discard the directive and the clickjacking restriction goes with it, so
 * the operator who asked for the strictest posture got none at all. An emptied allowlist means
 * "nobody may frame this", which is spelled `'none'`, so that is what it produces.
 *
 * @param {Record<string, string | undefined>} env
 * @returns {string} a non-empty `frame-ancestors` value
 */
export class WildcardOriginError extends Error {}

/**
 * Exact tokens that may never be a framing ancestor.
 *
 * The set exists for `null`, which the asterisk rule below cannot see: it carries no asterisk and
 * is a wildcard by BEHAVIOUR rather than by spelling, because a sandboxed iframe presents a null
 * origin, so `frame-ancestors null` admits framing from a document whose own origin the browser
 * has already discarded. The other three are already refused by the asterisk rule and are named
 * here anyway, so the refused vocabulary is one list a reader can check rather than something
 * they have to derive from two rules at once.
 */
const WILDCARD_TOKENS = new Set(["*", "'*'", "null", "*.*"]);

/**
 * True when a token may not be a framing ancestor: one of the named tokens, or anything carrying
 * an asterisk. Matching is exact, so `https://nullify.example` stays a perfectly good origin.
 *
 * @param {string} token
 * @returns {boolean}
 */
function isWildcard(token) {
  return WILDCARD_TOKENS.has(token) || token.includes("*");
}

export function frameAncestors(env) {
  const raw = env.NEXT_PUBLIC_FRAME_ANCESTORS;
  if (raw === undefined || raw === null) return "'self'";
  const named = raw.split(/\s+/).filter(Boolean);
  const wildcards = named.filter(isWildcard);
  if (wildcards.length) {
    throw new WildcardOriginError(
      `NEXT_PUBLIC_FRAME_ANCESTORS origin policy must never contain a wildcard, got ` +
        `${JSON.stringify(wildcards)}. A wildcard lets any page frame the console and drive ` +
        "it as the signed-in user, a partial one (https://*.example) trusts every " +
        "subdomain including one an attacker took, and `null` is the origin a sandboxed iframe " +
        "presents, which is the same permission spelled without an asterisk. Name each " +
        "permitted origin in full.",
    );
  }
  return named.join(" ") || "'none'";
}

/**
 * The X-Frame-Options equivalent of `frameAncestors`, or "" where none exists.
 *
 * Mirrors `_frame_options` in the backend. X-Frame-Options is the pre-CSP backstop for agents that
 * do not understand `frame-ancestors`, and it can express exactly two of the three states: `'self'`
 * is SAMEORIGIN and `'none'` is DENY. It cannot express an allowlist (ALLOW-FROM was never widely
 * implemented and is gone), so a named parent origin gets no backstop rather than a DENY that would
 * break the very embed it was configured for.
 *
 * @param {string} ancestors the resolved `frame-ancestors` value
 * @returns {string}
 */
export function frameOptions(ancestors) {
  if (ancestors === "'self'") return "SAMEORIGIN";
  if (ancestors === "'none'") return "DENY";
  return "";
}

/**
 * The full default-deny policy.
 *
 * `style-src` carries `'unsafe-inline'` because the Next runtime injects critical CSS and there is
 * no nonce path for it. `script-src` does NOT: it takes the per-request nonce plus
 * `'strict-dynamic'`, so the nonced bootstrap may load its own chunks and nothing else may run.
 * `object-src 'none'` removes the plugin-document escape hatch that `default-src` alone does not
 * close in every agent, and `base-uri 'self'` stops injected markup re-pointing every relative URL
 * on the page at an attacker origin.
 *
 * Passing no nonce yields the strict `'self'` form, which is correct for any response that is not
 * a Next-rendered document and WRONG for one that is: Next serves its hydration bootstrap as an
 * INLINE script carrying the Flight payload, so `script-src 'self'` blocks it, `__next_f` never
 * fills, React never attaches, and every control on the page is dead markup while the headers, the
 * type-check, the build and every test stay green.
 *
 * @param {Record<string, string | undefined>} env
 * @param {string} [nonce]
 * @returns {string}
 */
export function contentSecurityPolicy(env, nonce) {
  // Dev only: Turbopack's HMR client evaluates the module updates it receives and opens a
  // websocket back to the dev server. Without both relaxations `npm run dev` serves a page that
  // renders completely and never hydrates, which is the failure
  // `org-metadata/docs/demos/demo-inventory.md` records. Neither is ever emitted by a production
  // build: `next build` / `next start` set NODE_ENV=production, so the policy below comes out
  // byte-identical to the one this console shipped before the branch existed.
  const isDev = env.NODE_ENV !== "production";
  const connectSrc = ["'self'", apiOrigin(env), isDev ? "ws: wss:" : ""]
    .filter(Boolean)
    .join(" ");
  const scriptSrc = [
    "script-src 'self'",
    nonce ? `'nonce-${nonce}' 'strict-dynamic'` : "",
    isDev ? "'unsafe-eval'" : "",
  ]
    .filter(Boolean)
    .join(" ");
  return [
    "default-src 'self'",
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
    scriptSrc,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self' data:",
    `connect-src ${connectSrc}`,
    `frame-ancestors ${frameAncestors(env)}`,
  ].join("; ");
}

/** A fresh per-request nonce. Base64 of 16 random bytes from the Web Crypto global. */
export function generateNonce() {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes));
}

/** Raised when the nonce policy and the rendering mode disagree, which serves un-hydratable HTML. */
export class UnhydratableCspError extends Error {}

/**
 * Refuse a build whose CSP mints a nonce the rendered HTML can never carry.
 *
 * Next can only stamp a per-request nonce onto the scripts of a DYNAMICALLY rendered route. A
 * statically prerendered page was built before the nonce existed, so it emits bare script tags
 * while the header advertises a nonce, and because `'strict-dynamic'` switches off the `'self'`
 * fallback, that combination blocks strictly MORE than the unfixed policy did. The failure is
 * invisible to every check that does not execute the page, so it is refused at build time:
 * `next.config.mjs` calls this at module scope, and both `next build` and `next start` evaluate
 * that file.
 *
 * No I/O happens here. The caller passes the source as a string, which keeps this module
 * importable from the edge-runtime proxy.
 *
 * @param {string} layoutSource contents of `app/layout.tsx`
 * @throws {UnhydratableCspError}
 */
export function assertHydratableCsp(layoutSource) {
  if (!/export\s+const\s+dynamic\s*=\s*["']force-dynamic["']/.test(layoutSource)) {
    throw new UnhydratableCspError(
      'app/layout.tsx must set `export const dynamic = "force-dynamic"`. The CSP mints a ' +
        "per-request nonce, and Next can only stamp it onto script tags for a dynamically " +
        "rendered route. Statically prerendered HTML was built before the nonce existed, so " +
        "every script is blocked and the page never hydrates.",
    );
  }
}
