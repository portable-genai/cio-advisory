# `cio-advisory` CIO Advisory Assistant : System Specification

> Catalog id `cio-advisory` · group `doc` · priority **P1** · buyer **Wealth / Private Bank** ·
> service port **8091** · package `cio_advisory`.
>
> **Decision-support, NOT financial advice.** Every output is suitability-tagged, carries a
> non-advice disclaimer, and is maker-checker gated. The relationship manager (RM) is the
> human checker.

## 1. Purpose

`cio-advisory` is a grounded assistant for relationship managers in private banking. It does RAG over
the bank's **CIO house-view articles** (via the governed `enterprise-knowledge-base` knowledge base) and reads the
**client's portfolio**, then produces **personalised, suitability-checked talking points**.
It handles customer PII / financial data, so rule **R1** applies: the full `agent-guardrail-gateway` redaction +
guardrail pipeline runs on every request.

The assistant never advises. It surfaces discussion points, each tagged with a suitability
verdict and citations, for the RM to weigh and sign off.

## 2. Configuration & profiles

- **Region pinned** to `asia-southeast1` (Singapore) for residency. There is no global
  fallback.
- **Profiles** (env `CIO_PROFILE`, production default `gcp`): `gcp` (managed stack),
  `local` (a WORKING offline laptop stack, what dev/test/CI set explicitly), `platform` (delegate to
  sibling `agent-guardrail-gateway`, `enterprise-knowledge-base`, `agent-registry`, `model-quality-gate`, `agent-observability` services over HTTP), `onprem` (fail-fast placeholder adapters, the
  migration target).

| Profile | Backend per port | Notes |
|---|---|---|
| `gcp` | Managed Gemini Enterprise Agent Platform (lazy SDK) | Production default |
| `local` | House views: SQLite FTS5 (BM25). LLM: deterministic schema-driven. Guardrail: heuristic. DLP: regex. Audit: append-only SQLite WORM stand-in. Tracer: no-op. Sessions / memory / registry: in-process. Portfolio: **DuckDB, the same five tables the managed dataset holds**. Grounding: disabled. Eval: in-repo offline gate. | SDK-free, no API key, no emulator. Self-seeds the shipped fictional book. |
| `platform` | HTTP clients to `agent-guardrail-gateway` / `enterprise-knowledge-base` / `agent-registry` / `model-quality-gate` / `agent-observability` | Inside the full platform |
| `onprem` | Placeholders that raise `NotImplementedError` | Fail-fast migration target |

  **The client book.** The fictional clients, their holdings, the instruments they hold and
the model portfolio per risk profile ship as NDJSON under
`src/cio_advisory/data/demo_book/`, one file per BigQuery table and in that table's column
order. The DuckDB store the laptop reads and the BigQuery dataset the deployment reads are
filled from those same files, so the two surfaces are about one book rather than two that
resemble each other. `tests/contract/test_demo_book.py` holds the book's own invariants, the
console's client picker and the managed adapter's selected columns against the Terraform
schema; that last check exists because the adapter selected a `tenant` column the schema
never declared, which no offline test could see.

The `local` profile is SDK-free and emulator-free by default; for higher fidelity it
  routes the in-process stores (sessions / memory / registry) to Google's official Firestore
  emulator when `FIRESTORE_EMULATOR_HOST` is set AND the `[gcp]` extra is installed (the
  google client is imported lazily, only on that branch). There is no emulator for File
  Search, Gemini, Model Armor, DLP or BigQuery, so those stay on the SDK-free workaround.
- **Models** (pinned): reasoning `gemini-3.5-flash` (thinking=high) for talking-point
  synthesis; triage `gemini-3.5-flash`. Never a floating default or `gemini-2.0-flash`.
- **Grounding** (`grounding_enabled`, default off): public-web `google_search` corroboration
  via an isolated sub-agent (one built-in tool per agent).
- **Suitability** (`suitability.concentration_limit`, default 0.40): the single-asset-class
  weight at or above which an overweight theme is flagged REVIEW.

## 3. Pinned stack (the `[gcp]` extra)

| Concern | Managed service |
|---|---|
| House-view retrieval | Governed `enterprise-knowledge-base` (`/v1/search`); standalone: Agent Search / File Search |
| Portfolio + profile + instruments + model portfolios | BigQuery `wealth_portfolio` (internal data, CMEK, in-region), filled by `scripts/load_demo_book.py` |
| Reasoning / triage | Gemini on the Gemini Enterprise Agent Platform |
| Guardrail | Model Armor (`sanitizeUserPrompt` / `sanitizeModelResponse`) |
| PII redaction | Sensitive Data Protection / DLP (`deidentifyContent`) |
| Audit (WORM) | Cloud Logging locked bucket, retention 2557 days |
| Tracing | Cloud Trace via OpenTelemetry (message content capture OFF) |
| Eval gate | Gen AI evaluation service |
| Hosting | Agent Runtime (reasoningEngine) |

SDKs: `google-adk==2.7.1`, `google-genai`, `google-cloud-aiplatform[agent_engines,adk,evaluation]`,
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
4. **PortfolioSummary**: what the client holds against what their risk profile calls for.
   Every asset class the **ModelPortfolio** names, its current weight, its target and band,
   and an **AllocationGap** carrying the signed drift in weight and in money. Computed
   arithmetic, available without generating anything, so a console can show the
   before-picture the moment a client is picked.
5. **ThemeAlignment**: one CIO theme set against this portfolio. Its **ThemeSignal**
   (opportunity, threat or watch) is DERIVED from the stance so the two cannot disagree;
   `addresses` names the under-allocated class an opportunity would move towards target and
   `exposure` the class a threat bears on; `related_holdings` are matched by the instrument's
   theme tags, falling back to the asset class. Every talking point carries the alignment
   for its theme, so "this closes your equity gap" is arithmetic rather than a claim.

### Services & policies

- `AdvisoryService(house_view, portfolio, llm, guardrail, redaction, tracer, audit,
  suitability_policy=None, review_policy=None)` : `.brief(client_id, actor) -> AdvisoryBriefing`.
- `SuitabilityPolicy.assess(house_view, client, portfolio) -> SuitabilityAssessment`. The
  worst (most cautious) verdict across risk-appetite, constraint, concentration and
  knowledge factors wins. AGGRESSIVE-only themes are REVIEW for BALANCED and UNSUITABLE for
  CONSERVATIVE clients; hard-excluded asset classes are UNSUITABLE; a concentration breach
  forces REVIEW.
- `gap_analysis` : pure arithmetic and pure matching. `allocation_gaps` measures each asset
  class against the model portfolio's published band and names the positions whose values sum
  to each figure (`contributors`, by `instrument_id`) beside the read they came from
  (`evidence: DataCitation`); `align_theme` says what a theme closes
  or bears on; `rank_by_relevance` orders the day's themes by what they mean for this
  portfolio; `uncovered` names the under-allocated classes today's report is silent on, so a
  briefing declines to invent a theme rather than omitting the gap. **A gap is a distance
  from a published target, not the absence of an asset class**: the previous alignment asked
  only whether a class was present, so a client one point short and a client holding none
  read identically and a client at twice their target read as in line.
- `TalkingPointsService` : synthesise points (LLM) + attach suitability and the computed
  alignment; drop UNSUITABLE; filter named holdings to ones the client owns.
- `CioReviewPolicy` : a briefing always requires review; any REVIEW/UNSUITABLE point
  escalates the audit decision.

### Pipeline (R1 full safety; tracer.span; audited)

```
redaction.redact(inputs)
  -> guardrail.screen(INPUT)            [blocked -> audit BLOCKED + raise]
  -> portfolio.get_profile + get_portfolio + get_model_portfolio [None => no gaps]
  -> gap_analysis.summarise (allocation gaps: arithmetic, no model call)
  -> house_view.retrieve (`enterprise-knowledge-base`)           [empty -> RetrievalEmptyError]
  -> gap_analysis.rank_by_relevance (order, never filter)
  -> llm synthesise TalkingPoint[]  [model portfolio + gaps in the prompt context]
  -> SuitabilityPolicy.assess per point (drop/flag UNSUITABLE)
  -> attach the computed ThemeAlignment; drop holdings the client does not own
  -> compute PortfolioAlignment (gaps, theme links, uncovered gaps)
  -> attach not-advice disclaimer
  -> guardrail.screen(OUTPUT)           [blocked -> audit BLOCKED + raise]
  -> CioReviewPolicy (always requires review; escalate on REVIEW/UNSUITABLE)
  -> audit.record(redacted prompt + response)
```

## 6. HTTP API (this repo DEFINES)

All JSON field names mirror the domain dataclasses (enums as strings).

- `POST /v1/briefing {client_id}` -> `AdvisoryBriefing`, carrying the talking points, the
  portfolio summary with its allocation gaps, the whole report as `house_views_considered`
  (opportunities and threats alike, not only what survived suitability), and the alignment.

**Every allocation figure carries a data citation.** A briefing cites the documents behind
its narrative; the figures beside them are arithmetic over a client's book, and until they
were traceable a reader could not tell a computed number from a generated one. `DataCitation`
is that contract pointed at a table : which store answered (`duckdb` on a laptop, `bigquery`
on a deployment), which table, the predicate, the row count and the book's as-of date.
`PortfolioSummary.provenance` carries it for the summary and each `AllocationGap.evidence`
for one figure. It describes the READ and never repeats the rows: the holdings are on the
wire once, and `contributors` names which of them. `PortfolioPort.read_provenance` is where
each adapter reports its own; `None` is a real answer for an adapter that cannot say, and the
line is then absent rather than invented.
- `POST /v1/talking-points {client_id}` -> `{client_id, talking_points[],
  not_advice_disclaimer, requires_human_review}`.
- `POST /v1/suitability {client_id, theme}` -> `SuitabilityAssessment`.
- `GET /v1/clients/{client_id}/portfolio` -> `PortfolioSummary`: the holdings against the
  risk profile's model portfolio. Calls no model and retrieves nothing, so the console shows
  the before-picture the moment a client is picked rather than after a briefing is built.
  Entitlement-gated exactly like a briefing: a portfolio is the customer data the gate exists
  to protect.
- `GET /healthz` -> `{status, profile, region}`.
- `GET /v1/personas` -> `Persona[]` (seeded dev personas; the local-profile picker; `[]`
  outside `local`).
- `GET /v1/clients` -> the caller's tenant's clients, each with a PII-free label the SERVER
  derives from the profile, plus the book's version and whether it is fictional. The console
  carried its own hardcoded list of four until 2026-09-07, two of which the server did not
  serve at all.
- `GET /.well-known/agent-card.json` -> A2A AgentCard (skills: `build_briefing`,
  `generate_talking_points`, `check_suitability`).

No request body carries an `actor`: identity is resolved server-side by the IdentityPort
(`api/security.py`) and the verified `Principal` supplies the audit actor. Under `local` the
seeded persona is chosen with the `X-Dev-Persona` header; in secure mode it comes from the
IAP-injected assertion. See docs/embedding-and-identity.md.

### Sibling services `cio-advisory` CONSUMES

`PortfolioPort` additionally serves `get_model_portfolio(risk_appetite, jurisdiction)`, which
returns the bank's published allocation or `None`. It stays on this port rather than a new one
because an institution's strategic asset allocation is its own internal data, with no platform
hop, exactly like the holdings beside it.

- **`agent-guardrail-gateway`** (`GUARDRAIL_GATEWAY_URL`, default `:8080`): `POST /v1/guardrail/screen`,
  `POST /v1/redact`.
- **`enterprise-knowledge-base`** (`KNOWLEDGE_BASE_URL`, default `:8082`): `POST /v1/search` (house-view RAG).
- **`agent-registry`** (`AGENT_REGISTRY_URL`, default `:8083`): `POST /v1/agents`, `GET /v1/agents/{name}`.
- **`model-quality-gate` AI quality** (`QUALITY_GATE_URL`, default `:8084`, R5 gate): `POST /v1/evaluations`
  with a structured body `{target: {model, prompt_version, dataset_id, system}, dataset_id,
  bundle: "doc3-cio-advisory"}` (the top-level `dataset_id` must equal `target.dataset_id`);
  per-metric outcomes are read from `results[]` (not `metrics[]`). `POST /v1/gate` (same body)
  returns the single `{passed}` promotion decision. `model-quality-gate` selects the metric suite from the
  registered `doc3-cio-advisory` bundle, so the client sends no bare metric names.
- **`agent-observability`** (`OBSERVABILITY_URL`, default `:8085`): `POST /v1/audit`.

Validated by `architecture-validator` at intake (R6).

## 7. Eval gate (`eval/run_eval.py`)

Offline heuristic over synthetic `{client_profile, portfolio, house_views,
expected_suitability_verdicts}`, driving the real `AdvisoryService`. Metrics and thresholds:

| Metric | Threshold | Meaning |
|---|---|---|
| `groundedness` | 0.80 | talking points cited to a house view |
| `suitability_accuracy` | 0.85 | verdict matches the client's profile |
| `citation_accuracy` | 0.90 | cited sources were actually retrieved |
| `no_advice_safety` | 0.99 | output never phrased as advice, disclaimer present |
| `pii_safety` | 0.99 | no identifier survives redaction into the briefing or the audit |
| `gap_coverage` | 0.90 | of the gaps a correct briefing should close for this client, how many it speaks to |

The golden set is **rendered** from the shipped book by `scripts/render_golden.py`, so the
gate measures the clients the demo shows; `make eval` fails when the committed file is stale.
The expectations in `eval/expectations.json` are hand-written and are never derived from the
book: an oracle computed from the code under test agrees with it by construction. Writing it
by hand immediately found two verdicts the author had got wrong, which is the argument for
the separation in one line. `gap_coverage`'s denominator is hand-written for the same reason,
after the first version derived it from the briefing's own points and scored a clean 1.0 on a
briefing that closed no gaps at all.

## 8. Non-goals

`cio-advisory` does not execute trades, place orders, or move money. It does not provide financial
advice, a recommendation, or a suitability sign-off for the client: those remain with the
RM. The synthetic client/portfolio data is fictional and not for live client data without
sign-off.
