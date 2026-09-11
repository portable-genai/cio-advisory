# `cio-advisory` Operations Runbook

Operating the CIO Advisory Assistant service.

## Profiles

- `gcp`: standalone managed stack on the Gemini Enterprise Agent Platform.
- `platform`: delegate guardrail/redaction (`agent-guardrail-gateway`), house views (`enterprise-knowledge-base`), registry (`agent-registry`), eval (`model-quality-gate`),
  audit (`agent-observability`) to the shared sibling services over HTTP.
- `onprem`: placeholder adapters (migration target). Tests and CI run here.

Set `CIO_PROFILE`. The active profile and pinned region are reported at `GET /healthz`.

## Run locally

```bash
# Tests / lint / eval (no GCP SDK):
make test
make lint
make eval

# API (needs a real profile to serve live):
CIO_PROFILE=gcp make run-api      # uvicorn on :8091
```

## Endpoints

- `POST /v1/briefing {client_id}` : the full advisory briefing.
- `POST /v1/talking-points {client_id}` : just the talking points.
- `POST /v1/suitability {client_id, theme}` : one theme's suitability.
- `GET /healthz` : liveness, active profile, region.
- `GET /v1/personas` : seeded dev personas (local-profile picker; empty otherwise).
- `GET /.well-known/agent-card.json` : the A2A AgentCard.

The audit actor is never taken from the request body: it is the server-verified `Principal`
(an IAP assertion in secure mode; a seeded persona selected via the `X-Dev-Persona` header
under `local`). An unresolvable identity is a `401`. See `docs/embedding-and-identity.md`.

A guardrail block returns HTTP 200 with an explicit `blocked` envelope (flagged for human
review), never a 500. A missing portfolio or empty house-view result returns a 200
`unavailable` envelope.

## Common issues

| Symptom | Likely cause | Action |
|---|---|---|
| CLI exits with code 2, "not available under profile 'onprem'" | A placeholder adapter was hit | Use `CIO_PROFILE=gcp` or `platform` for live commands. |
| `RetrievalEmptyError` under `platform` | The `enterprise-knowledge-base` governed KB returned no house views | Check `KNOWLEDGE_BASE_URL` and that the CIO corpus is indexed there. |
| `RetrievalEmptyError` under `gcp` | The Agent Search store holds no records | Run `make ingest-house-views PROJECT=<id>`. Terraform creates the store empty. |
| `PortfolioUnavailableError` | No rows for the client in BigQuery | Confirm the client id and that the book is loaded (`make load-demo-book`). A client loaded under a different tenant reads as absent by design: the entitlement gate fails closed. |
| Briefing has fewer points than house views | UNSUITABLE points were dropped | Expected: unsuitable themes are never presented. Review the audit metadata `n_review_or_unsuitable`. |
| Eval gate fails on `no_advice_safety` | Output read as advice or missing disclaimer | A prompt or post-processing change leaked directive phrasing. Revert and re-run `python eval/run_eval.py`. |

## Loading the client book

The `gcp` and `platform` profiles read client profiles, holdings, instruments and model
portfolios from the `wealth_portfolio` BigQuery dataset. Terraform creates those tables and
leaves them empty; `scripts/load_demo_book.py` fills them with the shipped fictional book,
which is the same book the laptop serves from DuckDB.

```bash
make demo-book-dry-run TENANT=<hosted-domain>          # writes build/demo-book/*.ndjson, loads nothing
make load-demo-book PROJECT=<id> TENANT=<hosted-domain>
```

Three things decide whether this works.

**The tenant is not optional and `demo-bank` is not it.** Every client row carries the
tenant that owns it, and the entitlement gate compares that to the tenant the identity
adapter resolved from the IAP assertion: the tenant `CIO_IAP_TENANT_DOMAINS_JSON` maps the
caller's sign-in domain to, or the hosted domain itself where the map names none. Rows
loaded under any other value are invisible to every real user, and they read exactly like an
empty dataset. Pass the tenant the deployment's map resolves to. A caller also needs an
advisory role, which `CIO_IAP_GROUPS_JSON` grants by domain; without it a correctly tenanted
user is refused just the same. The shipped `client-000999` is loaded
under `<tenant>-other` instead, on purpose: it is the row that proves a user cannot reach
another tenant's client, and folding it in would delete that evidence.

**The loader truncates, so it refuses a book it did not write.** It proceeds only when the
target tables are empty or `book_manifest` says what they hold is fictional. Point it at a
real client book and it stops with the row counts it found.

**Terraform runs first.** The loader fills tables, it never creates them, and it says so
rather than half-loading. Changing a REQUIRED column on a `deletion_protection` table is a
replace, so apply the schema before there is anything in it worth keeping.

### The house-view store

The standalone `gcp` profile retrieves house views from an Agent Search data store, created
by `infra/terraform/house_views.tf` and filled by `scripts/ingest_house_views.py`:

```bash
make ingest-house-views PROJECT=<id>
```

Until it holds records the pipeline refuses every briefing with `RetrievalEmptyError`, which
is correct (nothing ungrounded is ever answered) and a confusing way to learn that a store
was never provisioned. The `platform` profile does not use it: retrieval there is delegated
to `enterprise-knowledge-base`.

Verify with a briefing that exercises the join and the tenant:

```bash
CIO_PROFILE=gcp cio-advisory briefing client-000418
```

## Audit and observability

- Every briefing writes an `AuditEvent` (already redacted) to the WORM sink. Decisions:
  `ALLOWED`, `ESCALATED` (a REVIEW/UNSUITABLE point was present), or `BLOCKED`.
- Trace spans (`advisory.brief`, `advisory.talking_points`) carry structural attributes
  only; message content capture is OFF (P-04).

## Promotion

The build must pass the offline eval gate (merge guard) and the `model-quality-gate` judged gate before
promotion (R5). Do not promote a build that fails `no_advice_safety` or
`suitability_accuracy`.
