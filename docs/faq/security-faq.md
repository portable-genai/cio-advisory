# Security FAQ

For an application-security team reviewing this repo before adopting it as a base. Answers
reflect the current code. Cross-references: [`ARCHITECTURE.md`](../../ARCHITECTURE.md),
[`COMPLIANCE.md`](../../COMPLIANCE.md),
[`docs/embedding-and-identity.md`](../embedding-and-identity.md).

### How is a request authenticated? Can a client spoof its identity?

No. Identity is resolved **server-side** from the transport context by an `IdentityPort`
adapter (`api/security.py`, `domain/identity.py`), never from the request body. The request
schemas carry no `actor` field (`api/schemas.py`), and any client-asserted actor or ACL is
discarded; the audit actor and the entitlement principal both come from the verified
`Principal`. Per profile: `local` = seeded dev personas (no IdP, offline only),
`gcp`/`platform` = the IAP-injected signed assertion verified on the service, `onprem` = a
client-IdP placeholder you implement. This repo deliberately does **not** ship its own web
login flow; the edge (IAP / Apigee) is the primary policy-enforcement point and the
`IdentityPort` is the inner ring of a defense-in-depth PEP.

### How is object-level authorization (client isolation) enforced?

Client access is gated server-side in `domain/entitlements.py`: the entitlement check runs
against the verified principal **before** the portfolio is loaded, so a client id is not a
capability. An unentitled request returns HTTP 403, not the client's portfolio or briefing.
Because the deterministic pipeline refuses to run on empty retrieval, a caller cannot coax
an ungrounded answer for a client they cannot see.

### What about the service-to-service calls in the `platform` profile?

The platform adapters (`adapters/platform/_s2s.py`) require `https://` base URLs outside
loopback (rejected at adapter construction). When `S2S_TOKEN` is set, every request
carries it as an `Authorization: Bearer` header, and `S2S_SIGNING_KEY` optionally
propagates the verified end-user actor as a signed header rather than a trust-me JSON field.
The receiving horizontal-platform and de-risking services own verification. The outbound
S2S machinery and the fail-closed network defaults come from the shared `hex-service-kit`
commons, so every catalog repo behaves the same way.

### Is the demo/dev server safe? Does anything bind 0.0.0.0 by default?

No. There are two bounds, and the load-bearing one rides the **app object** rather than an
entry point.

`main()` binds **loopback (127.0.0.1)** via `hex_service_kit.resolve_bind_host`. On its own
that is a property of one entry point, not of the application: the Dockerfile `CMD` is
`uvicorn cio_advisory.api.app:app --host 0.0.0.0`, and a `uvicorn ... --host 0.0.0.0` typed
by hand behaves the same way, so neither ever reaches that call. The real bound is
`add_loopback_exposure_guard`, registered on the app object as the outermost middleware, so
it holds however the service is started: a non-loopback peer is refused with a 503 before
CORS, before the header baseline and before any route or dependency runs.

**What switches it off is the identity BINDING, and nothing else.** The guard asks the
adapter bound to the identity port whether it verifies the end user (see
`src/cio_advisory/ports/identity.py`). The seeded persona adapter reads `X-Dev-Persona`, a
header the caller writes, so it declares `client-asserted` and the guard stays on; the
on-premises placeholder resolves nobody, so it declares `unimplemented` and the guard stays
on; only the IAP adapter, which verifies a signed assertion, declares `verified` and stands
the guard down. Note that the persona adapter is bound under `live` as well as `local`, so a
rule keyed on the profile name would have missed it.

`CIO_S2S_TOKEN` is deliberately **not** part of that decision. It authenticates a calling
service and no end user, so setting one closes the service-to-service dependency and changes
nothing about the end-user routes. A guard that read it would switch the bound off for
exactly the routes it protects the moment a service credential is set, and
`GET /v1/personas` would answer a LAN peer with the seeded approver persona, groups and
tenant included. `tests/unit/test_serving_path_exposure.py` is the standing proof that this
cannot happen.

`CIO_ALLOW_INSECURE_DEMO=1` remains the single documented opt-out. Secure profiles keep the
container-friendly `0.0.0.0` because ingress is fronted by the platform and the identity
adapter verifies the caller. The offline presenter demo server
(`scripts/cio_demo_server.py`, port 8099) is clearly dev-only and serves synthetic,
fictional data.

### What HTTP security headers are set? How is embedding controlled?

The API middleware emits a `Content-Security-Policy` with a `frame-ancestors` allowlist
(`CIO_FRAME_ANCESTORS`, which parent origins may iframe the assistant) and
`X-Frame-Options: SAMEORIGIN` for the same-origin case. CORS never uses `*`: origins come
from an explicit per-tenant allowlist (`CIO_CORS_ORIGINS`) built by
`hex_service_kit.cors_allowlist`, so a secure deploy that forgets to configure origins
trusts nothing cross-origin. The Next.js UI is intended to embed same-origin behind the
parent app's reverse proxy (no CORS needed) or run standalone against the allowlist.

### How tamper-evident is the audit trail? What are its limits?

The `local` audit store is `hex_service_kit.audit.HashChainedAuditLog`: an append-only
SQLite table where each row carries `entry_hash = SHA-256(prev_hash || event_json)` and
`UPDATE`/`DELETE` are blocked, with a `verify()` pass over the stored trail (control C9).
Records are already redacted before they are written. The hash chain alone cannot detect a
full rewrite or tail truncation (it carries no secret); in production the `gcp` profile uses
a Cloud Logging **locked WORM bucket** (retention configured in
`infra/terraform/logging_worm.tf`), which provides non-rewritability itself. This repo does
not *replace* the enterprise WORM audit system (**Hrz5**); it writes to it. See
[features-faq.md](features-faq.md) for the boundary.

### Is there rate limiting / request-size control?

Not in this repo. Rate limiting and request-size caps are expected to be enforced at the
edge (IAP / Apigee / load balancer), which is also the primary authentication point. Treat
that as a deploy-gate item; the in-app layer is authorization and redaction, not a WAF.

### Supply chain: are dependencies pinned and scanned?

Yes. Committed lockfiles (`requirements-dev.lock`, `requirements-gcp.lock`,
`ui/package-lock.json`) are installed in CI and the Docker build; the base image is pinned
by digest; GitHub Actions are SHA-pinned; `.github/dependabot.yml` proposes bumps; and a CI
job runs `pip-audit` over the lockfiles. `ruff` is pinned exactly (`ruff==0.15.18`). The
shared commons (`hex-service-kit`, `agent-eval-kit`, `pii-kit`, `review-kit`) are
pinned by git tag and resolve to exact SHAs in the lockfile, so there is no build-time
coupling to un-pinned code.

### Where are secrets? Are any committed?

No secret values are in the repo. `config/settings.yaml` stores only the **names** of env
vars holding secrets (`S2S_TOKEN`, `S2S_SIGNING_KEY`, and similar); values are read
at construction time and never logged. Every shipped client, portfolio and house-view
fixture uses obviously-fictional ids.

### What is explicitly out of scope / a residual risk?

- No in-app rate limiter or body-size cap; the edge owns that (see above).
- The hash chain needs the managed WORM bucket to resist a full rewrite or truncation.
- The `onprem` identity and storage adapters are fail-fast placeholders; wiring a real
  client IdP is adoption work.
- This is a reference build: run your own pen-test, threat model, and model-risk review
  before any live-data deployment (stated throughout the docs).
