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
| `RetrievalEmptyError` under `gcp` | The Agent Search store holds no house views for the caller's tenant | Run `make ingest-house-views PROJECT=<id> TENANT=<tenant>` (see below). Terraform creates the store empty, and a document under another tenant is invisible by design. |
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
by `infra/terraform/house_views.tf` and filled by `scripts/ingest_house_views.py`. Until it
holds records the pipeline refuses every briefing with `RetrievalEmptyError`, which is correct
(nothing ungrounded is ever answered) and a confusing way to learn that a store was never
provisioned. The `platform` profile does not use it: retrieval there is delegated to
`enterprise-knowledge-base`.

**Where the store is, is one setting.** Agent Search serves only `global`, `us` and `eu`, never
the deploy region. Terraform creates the store at `house_views_location` (default `us`) and
the API reads the same value from `CIO_HOUSE_VIEWS_LOCATION` (default `us`); the stack's
`house_views_api_env` output is that variable, ready to copy into the API's environment. The
loader takes no location flag: it writes wherever the API reads, through the API's own adapter,
so the two cannot be pointed at different places. Run the API (and the loader) with
`CIO_HOUSE_VIEWS_LOCATION` unset or equal to the Terraform value; an emptied variable refuses
to start, and a Cloud region is refused before any call.

```bash
make ingest-house-views-dry-run TENANT=<tenant>                 # prints the store path, the host and every record; writes nothing
make ingest-house-views PROJECT=<id> TENANT=<tenant>
```

**The tenant is the one the identity adapter resolves**, exactly as for the client book above:
every document carries it, and a briefing cites a tagged house view only for a caller verified
into the same tenant. A load under any other value reports success and every briefing reports
an empty store. The loader therefore requires `--tenant` and refuses an empty one.

**Re-running is safe.** Each document is compared with what the store holds: missing ones are
created, changed ones updated, identical ones left alone, and the run reports each group. A
document under a loaded id that another tenant owns stops the load before anything is written.
Documents this tenant holds that the shipped corpus no longer names are listed, never deleted.

**The loader needs the `[gcp]` extra and credentials, and the repository's own `.venv` has
neither** (the offline gate depends on it staying SDK-free). Build one outside the tree:

```bash
python3.12 -m venv ~/venvs/cio-gcp && ~/venvs/cio-gcp/bin/pip install -e ".[gcp]"
PYTHONPATH=src ~/venvs/cio-gcp/bin/python scripts/ingest_house_views.py --project <id> --tenant <tenant>
```

The dry run needs neither the extra nor credentials. Verify with a briefing through the deployed
console as a user of that tenant, or offline with `CIO_PROFILE=gcp cio-advisory briefing
client-000418` from the same venv; both must cite the loaded `cio-2026q3-...` documents.

## Audit and observability

- Every briefing writes an `AuditEvent` (already redacted) to the WORM sink. Decisions:
  `ALLOWED`, `ESCALATED` (a REVIEW/UNSUITABLE point was present), or `BLOCKED`.
- Trace spans (`advisory.brief`, `advisory.talking_points`) carry structural attributes
  only; message content capture is OFF (P-04).

## Promotion

The build must pass the offline eval gate (merge guard) and the `model-quality-gate` judged gate before
promotion (R5). Do not promote a build that fails `no_advice_safety` or
`suitability_accuracy`.

## Terraform state, and the one-time migration

This stack's state lives in the deployment's GCS bucket under the prefix `cio-advisory`;
`providers.tf` declares the backend partially, so the bucket is an init input:

```bash
cd infra/terraform
terraform init -input=false -backend-config=bucket=<state-bucket> -backend-config=prefix=cio-advisory
terraform plan
```

Or `make tf-plan TF_STATE_BUCKET=<state-bucket>` from the repository root.

**An installation applied before the backend existed** holds its state in a local, gitignored
`infra/terraform/terraform.tfstate`, which is the deployment's only record of the
`wealth_portfolio` dataset, its tables and the KMS key ring. Migrate it once, before any other
plan, and never start from an empty prefix instead: re-creating the BigQuery dataset that
already exists fails.

```bash
terraform init -migrate-state -backend-config=bucket=<state-bucket> -backend-config=prefix=cio-advisory
terraform plan   # expect no creates for the dataset, its tables or the key ring
```

Keep the local file until that plan is clean.
