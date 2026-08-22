# Doc3 CIO Advisory Assistant : System Specification

> Catalog id **Doc3** · group `doc` · priority **P1** · buyer **Wealth / Private Bank** ·
> service port **8091** · package `cio_advisory`.
>
> **Decision-support, NOT financial advice.** Every output is suitability-tagged, carries a
> non-advice disclaimer, and is maker-checker gated. The relationship manager (RM) is the
> human checker.

## 1. Purpose

Doc3 is a grounded assistant for relationship managers in private banking. It does RAG over
the bank's **CIO house-view articles** (via the governed Hrz2 knowledge base) and reads the
**client's portfolio**, then produces **personalised, suitability-checked talking points**.
It handles customer PII / financial data, so rule **R1** applies: the full Hrz1 redaction +
guardrail pipeline runs on every request.

The assistant never advises. It surfaces discussion points, each tagged with a suitability
verdict and citations, for the RM to weigh and sign off.

## 2. Configuration & profiles

- **Region pinned** to `asia-southeast1` (Singapore) for residency. There is no global
  fallback.
- **Profiles** (env `CIO_PROFILE`, production default `gcp`): `gcp` (managed stack),
  `local` (a WORKING offline laptop stack, what dev/test/CI set explicitly), `platform` (delegate to
  sibling Hrz1/Hrz2/Hrz3/Hrz4/Hrz5 services over HTTP), `onprem` (fail-fast placeholder adapters, the
  migration target).

| Profile | Backend per port | Notes |
|---|---|---|
| `gcp` | Managed Gemini Enterprise Agent Platform (lazy SDK) | Production default |
| `local` | House views: SQLite FTS5 (BM25). LLM: deterministic schema-driven. Guardrail: heuristic. DLP: regex. Audit: append-only SQLite WORM stand-in. Tracer: no-op. Sessions / memory / registry: in-process. Portfolio: in-process synthetic. Grounding: disabled. Eval: in-repo offline gate. | SDK-free, no API key, no emulator. Self-seeds a synthetic corpus. |
| `platform` | HTTP clients to Hrz1 / Hrz2 / Hrz3 / Hrz4 / Hrz5 | Inside the full platform |
| `onprem` | Placeholders that raise `NotImplementedError` | Fail-fast migration target |

  The `local` profile is SDK-free and emulator-free by default; for higher fidelity it
  routes the in-process stores (sessions / memory / registry) to Google's official Firestore
  emulator when `FIRESTORE_EMULATOR_HOST` is set AND the `[gcp]` extra is installed (the
  google client is imported lazily, only on that branch). There is no emulator for File
  Search, Gemini, Model Armor, DLP or BigQuery, so those stay on the SDK-free workaround.
- **Models** (pinned): reasoning `gemini-3.5-flash` (thinking=high) for talking-point
  synthesis; triage `gemini-3.1-flash-lite`. Never a floating default or `gemini-2.0-flash`.
- **Grounding** (`grounding_enabled`, default off): public-web `google_search` corroboration
  via an isolated sub-agent (one built-in tool per agent).
- **Suitability** (`suitability.concentration_limit`, default 0.40): the single-asset-class
  weight at or above which an overweight theme is flagged REVIEW.

## 3. Pinned stack (the `[gcp]` extra)

| Concern | Managed service |
|---|---|
| House-view retrieval | Governed Hrz2 KB (`/v1/search`); standalone: Agent Search / File Search |
| Portfolio + profile | BigQuery (internal data, CMEK, in-region) |
| Reasoning / triage | Gemini on the Gemini Enterprise Agent Platform |
| Guardrail | Model Armor (`sanitizeUserPrompt` / `sanitizeModelResponse`) |
| PII redaction | Sensitive Data Protection / DLP (`deidentifyContent`) |
| Audit (WORM) | Cloud Logging locked bucket, retention 2557 days |
| Tracing | Cloud Trace via OpenTelemetry (message content capture OFF) |
| Eval gate | Gen AI evaluation service |
| Hosting | Agent Runtime (reasoningEngine) |

SDKs: `google-adk==2.3.0`, `google-genai`, `google-cloud-aiplatform[agent_engines,adk,evaluation]`,
`google-cloud-discoveryengine`, `google-cloud-bigquery`, `google-cloud-dlp`,
`google-cloud-logging`, `opentelemetry-*`, `a2a-sdk`, `mcp`.

## 4. Architecture (hexagonal ports-and-adapters)

- **Domain core** (`domain/`): pure standard library. Frozen dataclasses, enums, the
  `AdvisoryService`, the `SuitabilityPolicy` (the regulatory heart), the
  `TalkingPointsService`, the `CioReviewPolicy`, prompts, serialization, errors.
- **Ports** (`ports/`): `@runtime_checkable` Protocols only.
- **Adapters** (`adapters/{gcp,platform,onprem}/`): GCP managed (lazy SDK imports),
  platform HTTP clients to siblings, on-prem placeholders that raise `NotImplementedError`.
- **Wiring** (`config.py` + `config/settings.yaml`): the container binds each port to an
  adapter by dotted path per the active profile.
- **Edges**: `api/` (FastAPI), `cli/` (Typer), `agent/` (ADK root agent + tools + callbacks
  + grounding sub-agent).

No `google-cloud-*` import runs at module import time: the on-prem/test profile installs no
GCP SDK.

## 5. Artifacts, services & the pipeline

### Artifacts

1. **AdvisoryBriefing**: the deliverable for one client, bundling the talking points, a
   portfolio alignment summary, and the mandatory `not_advice_disclaimer`. Always
   `requires_human_review = True`.
2. **TalkingPoint[]**: each a personalised point (headline + body) linking a CIO house-view
   theme to the client's holdings, with its `SuitabilityAssessment` and citations.
   `is_advice = False`.
3. **SuitabilityAssessment**: per theme, a verdict (SUITABLE | REVIEW | UNSUITABLE) against
   the client's risk profile, objectives, knowledge/experience and concentration, with
   factors + rationale + citations. UNSUITABLE points are dropped, never recommended.

### Services & policies

- `AdvisoryService(house_view, portfolio, llm, guardrail, redaction, tracer, audit,
  suitability_policy=None, review_policy=None)` : `.brief(client_id, actor) -> AdvisoryBriefing`.
- `SuitabilityPolicy.assess(house_view, client, portfolio) -> SuitabilityAssessment`. The
  worst (most cautious) verdict across risk-appetite, constraint, concentration and
  knowledge factors wins. AGGRESSIVE-only themes are REVIEW for BALANCED and UNSUITABLE for
  CONSERVATIVE clients; hard-excluded asset classes are UNSUITABLE; a concentration breach
  forces REVIEW.
- `TalkingPointsService` : synthesise points (LLM) + attach suitability; drop UNSUITABLE.
- `CioReviewPolicy` : a briefing always requires review; any REVIEW/UNSUITABLE point
  escalates the audit decision.

### Pipeline (R1 full safety; tracer.span; audited)

```
redaction.redact(inputs)
  -> guardrail.screen(INPUT)            [blocked -> audit BLOCKED + raise]
  -> portfolio.get_profile + get_portfolio
  -> house_view.retrieve (Hrz2)           [empty -> RetrievalEmptyError]
  -> llm synthesise TalkingPoint[]
  -> SuitabilityPolicy.assess per point (drop/flag UNSUITABLE)
  -> compute PortfolioAlignment
  -> attach not-advice disclaimer
  -> guardrail.screen(OUTPUT)           [blocked -> audit BLOCKED + raise]
  -> CioReviewPolicy (always requires review; escalate on REVIEW/UNSUITABLE)
  -> audit.record(redacted prompt + response)
```

## 6. HTTP API (this repo DEFINES)

All JSON field names mirror the domain dataclasses (enums as strings).

- `POST /v1/briefing {client_id}` -> `AdvisoryBriefing`.
- `POST /v1/talking-points {client_id}` -> `{client_id, talking_points[],
  not_advice_disclaimer, requires_human_review}`.
- `POST /v1/suitability {client_id, theme}` -> `SuitabilityAssessment`.
- `GET /healthz` -> `{status, profile, region}`.
- `GET /v1/personas` -> `Persona[]` (seeded dev personas; the local-profile picker; `[]`
  outside `local`).
- `GET /.well-known/agent-card.json` -> A2A AgentCard (skills: `build_briefing`,
  `generate_talking_points`, `check_suitability`).

No request body carries an `actor`: identity is resolved server-side by the IdentityPort
(`api/security.py`) and the verified `Principal` supplies the audit actor. Under `local` the
seeded persona is chosen with the `X-Dev-Persona` header; in secure mode it comes from the
IAP-injected assertion. See docs/embedding-and-identity.md.

### Sibling services Doc3 CONSUMES

- **Hrz1 guardrail** (`HRZ_GUARDRAIL_URL`, default `:8080`): `POST /v1/guardrail/screen`,
  `POST /v1/redact`.
- **Hrz2 enterprise KB** (`HRZ_KB_URL`, default `:8082`): `POST /v1/search` (house-view RAG).
- **Hrz3 registry** (`HRZ_REGISTRY_URL`, default `:8083`): `POST /v1/agents`, `GET /v1/agents/{name}`.
- **Hrz4 AI quality** (`HRZ_QUALITY_URL`, default `:8084`, R5 gate): `POST /v1/evaluations`
  with a structured body `{target: {model, prompt_version, dataset_id, system}, dataset_id,
  bundle: "doc3-cio-advisory"}` (the top-level `dataset_id` must equal `target.dataset_id`);
  per-metric outcomes are read from `results[]` (not `metrics[]`). `POST /v1/gate` (same body)
  returns the single `{passed}` promotion decision. Hrz4 selects the metric suite from the
  registered `doc3-cio-advisory` bundle, so the client sends no bare metric names.
- **Hrz5 observability** (`HRZ_OBSERVABILITY_URL`, default `:8085`): `POST /v1/audit`.

Validated by **Rsk3** at intake (R6).

## 7. Eval gate (`eval/run_eval.py`)

Offline heuristic over synthetic `{client_profile, portfolio, house_views,
expected_suitability_verdicts}`, driving the real `AdvisoryService`. Metrics and thresholds:

| Metric | Threshold | Meaning |
|---|---|---|
| `groundedness` | 0.80 | talking points cited to a house view |
| `suitability_accuracy` | 0.85 | verdict matches the client's profile |
| `citation_accuracy` | 0.90 | cited sources were actually retrieved |
| `no_advice_safety` | 0.99 | output never phrased as advice, disclaimer present |

## 8. Non-goals

Doc3 does not execute trades, place orders, or move money. It does not provide financial
advice, a recommendation, or a suitability sign-off for the client: those remain with the
RM. The synthetic client/portfolio data is fictional and not for live client data without
sign-off.
