# Embedding and identity: client integration guide (B3 cio-advisory)

This guide shows how an enterprise client runs the B3 CIO Advisory Assistant and, when
desired, embeds its UI inside an existing web application (for example a relationship-manager
workbench) with secure single sign-on, so users never see a second login. It is grounded in
what this repository implements today: the server never trusts a client-asserted identity, and
every artifact route derives the audit actor from a server-verified `Principal`.

The three deployment shapes below (embedded same-origin, standalone behind IAP, local dev)
need no application code changes to integrate: the work is operational (choose a profile, set
a few environment variables, add a reverse-proxy route plus an iframe tag). Cross-origin
embedding, per-hop token exchange, and a redirect login are deliberately out of scope for this
slice; they are summarised in "Further layers" at the end, with a pointer to the reference
implementation.

---

## 1. The two pieces

The assistant ships as two cooperating pieces:

- **Backend**: a FastAPI service (default port `8091`) exposing the advisory endpoints
  (`/v1/briefing`, `/v1/talking-points`, `/v1/suitability`), health (`/healthz`), the seeded
  persona list (`/v1/personas`), and the A2A agent card (`/.well-known/agent-card.json`).
- **UI**: a Next.js console (default port `3000`) that calls the backend and renders the
  suitability-checked briefing. `NEXT_PUBLIC_EMBED=1` drops the UI's own chrome
  (`ui/app/layout.tsx`); the UI base path and API base are build-time env vars
  (`ui/next.config.mjs`, `ui/lib/api.ts`).

---

## 2. Deployment shapes

Pick the cheapest shape the host can actually satisfy.

| # | Shape | Use when the host... | Host work | Identity |
|---|-------|----------------------|-----------|----------|
| 1 | **Embedded, same-origin reverse proxy** | controls its own edge (nginx or Next.js rewrites) and can federate its IdP into Cloud IAP. | Two proxy routes (`/advisory/*`, `/advisory/api/*`) plus one `<iframe src="/advisory/">`. | IAP-verified `x-goog-iap-jwt-assertion` (`adapters/gcp/iap_identity.py`); the proxy forwards the header. |
| 2 | **Standalone behind Cloud IAP** | has no host app, or wants a separate console at its own URL. | DNS plus HTTPS load balancer plus IAP. | IAP-verified assertion; IAP plus Workforce Identity Federation gives silent SSO. |
| 3 | **Local dev, no auth** | is evaluating offline, no IdP. | None. | Seeded dev personas via `X-Dev-Persona` (`adapters/local/identity.py`). |

Because the embedded iframe (shape 1) is first-party (same origin), there are no
third-party-cookie problems and no CORS to configure.

---

## 3. Shape 1 (implemented): embed via same-origin reverse proxy

Serve the assistant under your own origin at a sub-path (for example `/advisory/`) via a
reverse proxy, then drop an iframe pointing at that same-origin path. The client owns exactly
two things: a proxy route, and an iframe tag.

### 3a. Reverse-proxy `/advisory/*` to the assistant service

**nginx**:

```nginx
# On https://workbench.client.com
location /advisory/ {
    proxy_pass         http://advisory-ui.internal:3000/;    # the Next.js UI
    proxy_set_header   Host              $host;
    proxy_set_header   X-Forwarded-Proto $scheme;
    proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
}

# The UI's API calls (NEXT_PUBLIC_API_BASE=/advisory/api) resolve same-origin:
location /advisory/api/ {
    proxy_pass         http://advisory-backend.internal:8091/;
    proxy_set_header   Host              $host;
    proxy_set_header   X-Forwarded-Proto $scheme;
    # IAP runs in front of this origin, so x-goog-iap-jwt-assertion is present on
    # the inbound request and is forwarded through to the backend.
}
```

**Next.js host app** (if the parent is itself Next.js, use `rewrites()` in its own config):

```js
// next.config.mjs of the PARENT app
const nextConfig = {
  async rewrites() {
    return [
      { source: "/advisory/api/:path*", destination: "http://advisory-backend.internal:8091/:path*" },
      { source: "/advisory/:path*",     destination: "http://advisory-ui.internal:3000/:path*" },
    ];
  },
};
export default nextConfig;
```

### 3b. Mount the UI under the sub-path and hide its chrome

```bash
# Environment for the assistant UI (build-time)
NEXT_PUBLIC_BASE_PATH=/advisory      # mount the UI (and assets) under the sub-path
NEXT_PUBLIC_API_BASE=/advisory/api   # same-origin API calls (no CORS needed)
NEXT_PUBLIC_EMBED=1                  # hide the UI's own header/nav chrome when embedded
```

### 3c. The iframe tag (host page)

```html
<!-- On https://workbench.client.com, inside your existing page -->
<iframe
  src="/advisory/"
  title="CIO Advisory Assistant"
  style="width:100%; height:100%; border:0;"
  loading="lazy">
</iframe>
```

Height caveat: `height:100%` renders correctly only inside a host container that already has a
fixed pixel height. There is no child-to-parent resize message in this slice, so give the
iframe a sized container.

### 3d. Allow the parent origin to frame the UI (implemented)

The backend emits `Content-Security-Policy: frame-ancestors <CIO_FRAME_ANCESTORS>` via
middleware (`api/app.py`), and adds `X-Frame-Options: SAMEORIGIN` only when the value is
`'self'` (the legacy header cannot express a multi-origin allowlist, so the multi-origin case
is left to CSP):

```bash
export CIO_FRAME_ANCESTORS="https://workbench.client.com"
# multiple parents are space-separated, per the CSP grammar:
# export CIO_FRAME_ANCESTORS="https://workbench.client.com https://admin.client.com"
```

Scope limit: `frame-ancestors` is honoured only on the HTTP response of the document the
browser actually frames, and only as a real response header (not a `<meta>` element). In this
same-origin shape the framed document is served through the proxy, so the backend header
reaches the browser.

The console serves its own half of the same posture with `NEXT_PUBLIC_FRAME_ANCESTORS`, read in
the same three states (`ui/lib/csp.mjs`): unset keeps `'self'`, a value naming no origin becomes
`'none'` rather than an empty directive that browsers discard as a parse error, and named parent
origins are space-separated. Set both variables to the same value.

### 3e. The console's own Content-Security-Policy (implemented)

The backend middleware covers API responses; the document a browser parses and executes is served
by Next, so the document-layer policy is built in `ui/lib/csp.mjs` and emitted in exactly one
place, `ui/proxy.ts`. `next.config.mjs` deliberately sets no CSP at all: two layers each emitting
one makes the browser intersect them, and the stricter value wins on every directive.

`script-src` carries a per-request nonce plus `'strict-dynamic'`. That is not decoration. Next
ships its hydration bootstrap as an INLINE script carrying the Flight payload, so a nonce-less
`script-src` blocks it, `__next_f` never fills, React never attaches, and every control renders as
dead markup while the headers, the type-check, the build and the tests all stay green.

Two things must both hold or the policy fails in opposite directions, so both are enforced:

- `app/layout.tsx` sets `export const dynamic = "force-dynamic"`. Next can only stamp a
  per-request nonce onto a dynamically rendered route; a statically prerendered page was built
  before the nonce existed, and because `'strict-dynamic'` switches off the `'self'` fallback,
  adding a nonce to a static route blocks strictly MORE than the unfixed policy did.
  `assertHydratableCsp`, called from `next.config.mjs`, fails `next build` and `next start` if the
  line is removed.
- `ui/scripts/assert-hydratable.mjs` (run by `make ui-check`) starts the BUILT server, fetches the
  served document, and asserts every `<script>` tag carries the nonce from the served header. A
  header assertion cannot see this failure: the header is byte-identical in the working case and
  in the broken one.

---

## 4. Shape 2 (implemented): standalone behind Cloud IAP

When there is no host application, deploy the assistant on its own URL:

1. Deploy backend and UI behind the same HTTPS load balancer and Cloud IAP.
2. Set `CIO_PROFILE=gcp` and `CIO_IAP_AUDIENCE` so the backend verifies the IAP assertion.
3. Point the UI at the backend with `NEXT_PUBLIC_API_BASE`. If UI and backend are on different
   origins, also set `CIO_CORS_ORIGINS` to the UI origin (explicit allowlist, never `"*"`):

   ```bash
   export CIO_CORS_ORIGINS="https://advisory.client.com"
   export NEXT_PUBLIC_API_BASE="https://api.advisory.client.com"
   ```

4. Share the URL with authorized users. IAP plus Workforce Identity Federation gives SSO from
   the corporate IdP (change who authenticates, not the code).

Leave `CIO_FRAME_ANCESTORS` at its `'self'` default: nothing should iframe a standalone
deployment.

---

## 5. Shape 3 (implemented): run locally, no auth

Local mode (`CIO_PROFILE=local`, which must be set deliberately) runs the entire pipeline
offline: SQLite-backed retrieval, a deterministic LLM, and no IdP, AD, or LDAP. An UNSET
`CIO_PROFILE` still binds the offline adapters, so a process starts, but it is not read as
choosing `local`: the seeded personas are refused with a 401 and the localhost CORS fallback
does not apply, because a lost environment variable must not publish an unauthenticated API. Identity is resolved from a small set
of seeded dev personas (`adapters/local/identity.py`) selected by an `X-Dev-Persona` request
header, with the first persona as the default.

```bash
# Backend (repo root)
export CIO_PROFILE=local
make run-api                      # uvicorn on http://localhost:8091

# UI (in ./ui)
npm install && npm run dev        # http://localhost:3000, NEXT_PUBLIC_API_BASE defaults to :8091
```

The UI fetches `GET /v1/personas` and sends the chosen id as `X-Dev-Persona`. The seeded
personas deliberately span different entitlements and tenants, so per-user and per-tenant
authorization is demoable offline:

| Persona id | Subject | Tenant | Entitlement principals |
|-----------|---------|--------|------------------------|
| `analyst` | `demo.analyst@bank.example` | `demo-bank` | `group:cio-analyst`, `group:risk` |
| `approver` | `demo.approver@bank.example` | `demo-bank` | `group:cio-analyst`, `group:risk`, `group:cio-approver` |
| `auditor` | `demo.auditor@bank.example` | `demo-bank` | `group:audit` |
| `other-tenant` | `user@other-tenant.example` | `other-bank` | `group:cio-analyst` |

```bash
curl -s http://localhost:8091/v1/personas | python -m json.tool
curl -s -X POST http://localhost:8091/v1/briefing \
  -H 'Content-Type: application/json' -H 'X-Dev-Persona: auditor' \
  -d '{"client_id": "client-000042"}' | python -m json.tool
```

In secure profiles `X-Dev-Persona` is ignored entirely (Section 6), and `/v1/personas` returns
an empty list, so leaving the persona picker in the UI is harmless in production: it renders
only when `GET /healthz` reports `profile === "local"`.

---

## 6. The identity contract

The single invariant, implemented today and preserved across every shape: the server never
trusts a client-asserted actor.

- `get_principal` (`api/security.py`) builds a `RequestContext` from inbound headers only,
  asks the active `IdentityPort` adapter to resolve a verified `Principal`, and a failure is a
  hard `401`.
- Every artifact route takes `principal: CurrentPrincipal` and passes `actor=principal.actor`
  into the advisory service. The request schemas (`ClientRequest`, `SuitabilityRequest` in
  `api/schemas.py`) carry no `actor` field, so any client-supplied identity is ignored.
- The `Principal` (`domain/identity.py`) models `subject` (the audit actor), `principals`
  (entitlement groups), `tenant` (multi-tenant partition), `assurance` (auth-strength hint),
  and `source` (which adapter resolved it).

The active profile selects the adapter, exactly like every other port:

| Profile | Adapter | What it does |
|---------|---------|--------------|
| `local` | `LocalPersonaIdentityAdapter` | Offline dev/test identity via `X-Dev-Persona`, no IdP. Default persona when the header is absent; an unknown id is a `401`. |
| `gcp` / `platform` | `IapIdentityAdapter` | Verifies the signed `x-goog-iap-jwt-assertion` (signature, issuer, audience, expiry) against Google's IAP public keys. `tenant` from the `hd` claim. Audience from `CIO_IAP_AUDIENCE`; the assertion is never logged. |
| `onprem` | `OnPremIdentityAdapter` | Fail-closed placeholder: raises `NotImplementedError` rather than returning an anonymous identity. Implement verification against your own enterprise IdP (OIDC/SAML) here. |

Defense in depth (PEP): the edge (Cloud IAP / Apigee) authenticates at ingress, the `agent-guardrail-gateway` applies central policy, and this backend independently re-verifies the assertion and
derives identity itself. Each layer assumes the others may be bypassed. This is the seam that
defeats actor spoofing and the confused-deputy risk.

---

## 7. Configuration reference

| Variable | Side | Purpose |
|----------|------|---------|
| `CIO_PROFILE` | backend | `local` \| `gcp` \| `platform` \| `onprem`. Selects the identity adapter (and the whole adapter set). |
| `CIO_IAP_AUDIENCE` | backend | The IAP audience string (the exact structured resource path) the backend verifies against. Required in `gcp`/`platform`. |
| `CIO_CORS_ORIGINS` | backend | Explicit origin allowlist for the cross-origin / standalone case. Comma-separated. Never `"*"`. Defaults to the dev origins. |
| `CIO_FRAME_ANCESTORS` | backend | CSP `frame-ancestors` allowlist: parent origins permitted to iframe the UI. Space-separated. Defaults to `'self'`. |
| `NEXT_PUBLIC_API_BASE` | UI | Backend base URL the UI calls, and the origin `connect-src` widens to. Must be absolute. Build-time. |
| `NEXT_PUBLIC_FRAME_ANCESTORS` | UI | CSP `frame-ancestors` for the console document itself. Space-separated. Unset is `'self'`; set-but-naming-nothing is `'none'`. Mirror `CIO_FRAME_ANCESTORS`. |
| `NEXT_PUBLIC_BASE_PATH` | UI | Sub-path the UI is mounted under (blank keeps standalone). Build-time. |
| `NEXT_PUBLIC_EMBED` | UI | Set to `1` to hide the UI's own chrome. Build-time. |
| `X-Dev-Persona` | request header | Local profile only. Selects a seeded dev persona; ignored in secure profiles. |

---

## 8. Checklists

### Client-side integration checklist

**Shape 1 (same-origin reverse proxy):**

- [ ] Reverse-proxy route mapping `/advisory/*` to the UI service (3a).
- [ ] Reverse-proxy route mapping `/advisory/api/*` to the backend service.
- [ ] `<iframe src="/advisory/">` on the host page in a sized container (3c).
- [ ] `CIO_FRAME_ANCESTORS` set to the exact parent origin(s) (3d).
- [ ] Build the UI with `NEXT_PUBLIC_BASE_PATH`, `NEXT_PUBLIC_API_BASE`, `NEXT_PUBLIC_EMBED=1` (3b).
- [ ] IdP federated into IAP so users carry one session through.

**Shape 2 (standalone):**

- [ ] DNS plus HTTPS load balancer plus IAP fronting the deployment.
- [ ] `CIO_PROFILE=gcp` and `CIO_IAP_AUDIENCE` set so the backend verifies the assertion.
- [ ] `CIO_CORS_ORIGINS` set if UI and backend are on different origins.
- [ ] URL shared with authorized users/groups.

### Security checklist

- [ ] HTTPS everywhere (the load balancer terminates TLS; IAP requires it).
- [ ] IAP audience configured: `CIO_IAP_AUDIENCE` set to the exact protected-resource path in
      any IAP profile (the backend refuses to verify without it).
- [ ] Framing locked down: `CIO_FRAME_ANCESTORS` set to the exact parent origin(s), `'self'`
      for standalone, never a wildcard.
- [ ] Origins locked down: same-origin proxy (no CORS) for shape 1, otherwise
      `CIO_CORS_ORIGINS` is an explicit allowlist, never `"*"`.
- [ ] No client-asserted identity trusted: production uses `gcp`/`platform` (or an implemented
      `onprem`), never `local`.
- [ ] No `actor` in any request body: the audit actor is the verified `Principal` (a body
      `actor` would be ignored, but do not send one).

---

## 9. Further layers (out of scope for this slice)

The shapes above cover a cooperative host that controls its edge and is GCP-aligned. Broader
host support and deeper hardening are deliberately not built here. Each is a clean addition on
an existing seam, and each is implemented in the reference repository
`cdd-sow-research` (`docs/embedding-and-identity.md`), which this guide mirrors:

- **Cross-origin token-handoff embedding** (loader plus web component plus a versioned
  `postMessage` contract, bearer-token-in-memory rather than third-party cookies) for SaaS
  tenants and pure SPAs that cannot run a proxy or federate into IAP. Adds a front-end embed
  product plus a JWKS-verifying identity adapter behind the same `IdentityPort` seam.
- **Cross-origin via server-side header injection**: a thin proxy injects
  `Authorization: Bearer <host token>`; same new JWKS adapter, token arrives via header.
- **Launch-in-new-tab (OIDC redirect login)**: a standalone shape verifying a self-issued
  session cookie minted after an OIDC Authorization Code plus PKCE login, for any host with an
  OIDC IdP that will not federate into IAP.
- **Per-hop hardening**: RFC 8693 OAuth2 token exchange (on-behalf-of) plus Workload Identity
  and mTLS to the Hrz platform services; step-up assurance (`acr`/`amr`) for consequential
  actions such as approver sign-off; per-tenant `frame-ancestors`/CORS/issuer policy resolved
  at request time; a fail-closed tenant predicate and ACLs in governed retrieval; a full CSP
  (nonce-based `script-src`, Trusted Types) on the framed UI document.
