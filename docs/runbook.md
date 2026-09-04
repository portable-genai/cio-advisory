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
| `RetrievalEmptyError` | The `enterprise-knowledge-base` governed KB returned no house views | Check `KNOWLEDGE_BASE_URL` and that the CIO corpus is indexed in `enterprise-knowledge-base`. |
| `PortfolioUnavailableError` | No rows for the client in BigQuery | Confirm the client id and that the portfolio/profile tables are populated. |
| Briefing has fewer points than house views | UNSUITABLE points were dropped | Expected: unsuitable themes are never presented. Review the audit metadata `n_review_or_unsuitable`. |
| Eval gate fails on `no_advice_safety` | Output read as advice or missing disclaimer | A prompt or post-processing change leaked directive phrasing. Revert and re-run `python eval/run_eval.py`. |

## Audit and observability

- Every briefing writes an `AuditEvent` (already redacted) to the WORM sink. Decisions:
  `ALLOWED`, `ESCALATED` (a REVIEW/UNSUITABLE point was present), or `BLOCKED`.
- Trace spans (`advisory.brief`, `advisory.talking_points`) carry structural attributes
  only; message content capture is OFF (P-04).

## Promotion

The build must pass the offline eval gate (merge guard) and the `model-quality-gate` judged gate before
promotion (R5). Do not promote a build that fails `no_advice_safety` or
`suitability_accuracy`.
