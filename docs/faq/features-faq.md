# Features FAQ

For product, compliance, and delivery teams: what this assistant does, what is deterministic
vs LLM, and, importantly, where its responsibilities **stop** and a sibling catalog system
takes over. Cross-references: [`README.md`](../../README.md), [`DEMO.md`](../../DEMO.md),
[`SPEC.md`](../../SPEC.md).

### What does Doc3 actually produce?

An `AdvisoryBriefing` for one client: personalised `TalkingPoint`s that each link a CIO
house-view theme to the client's holdings, a portfolio-alignment summary, and a mandatory
non-advice disclaimer. Every talking point carries a `SuitabilityAssessment`
(SUITABLE / REVIEW / UNSUITABLE) against the client's risk profile, objectives, knowledge and
concentration, with factors, rationale and citations. UNSUITABLE points are **dropped**,
never shown as a recommendation; REVIEW points are flagged. Empty retrieval is a hard error,
so the assistant never answers ungrounded.

### Is this financial advice?

**No.** It is decision-support. Talking points are `is_advice = False`, carry a non-advice
disclaimer, and are maker-checker gated. The relationship manager (RM) is the human checker
and owns any advice given to the client. The `no_advice_safety` eval metric (threshold 0.99)
fails the build if any output reads as advice or the disclaimer is missing.

### What is deterministic vs done by the LLM?

The consequential logic is **deterministic and replayable** (pure stdlib, unit-tested): the
`SuitabilityPolicy` (the regulatory heart, the most heavily tested module) and the
portfolio-alignment math. The LLM (`domain/talking_points_service.py`) only **narrates** the
themes into talking points. An auditor can recompute every suitability verdict and the
alignment without the model. This is by design (the "deterministic domain service" pattern).

### Is anything auto-approved?

No. Every `AdvisoryBriefing` sets `requires_human_review = True` (maker-checker, P-06); the
assistant proposes and the RM disposes. REVIEW / UNSUITABLE signals *raise* the review bar and
route the escalation to the Hrz7 Human-Review & Maker-Checker Console (rule R8); they never
lower it and never auto-execute.

### Which capabilities does this repo own vs integrate from the catalog?

This is one system in a catalog of composable GRC systems. It **owns** the advisory /
suitability domain logic and its outputs. It **integrates** (via the `platform` profile's HTTP
adapters) several cross-cutting concerns owned by sibling platform systems; do not rebuild
these in a fork:

| Concern | Owned by (catalog id / repo) | Doc3's role |
|---|---|---|
| Runtime guardrail: PII redaction, prompt-injection / jailbreak defense | **Hrz1** `agent-guardrail-gateway` | consumes it on every briefing (input + output screen) |
| Governed RAG / ACL-aware knowledge base that serves the CIO house views | **Hrz2** `enterprise-knowledge-base` | retrieves grounded, cited house views from it (R3); builds no separate retrieval backend |
| Agent registry, versioning, identity, entitlements | **Hrz3** `agent-registry` | publishes its A2A AgentCard for discovery (R4) |
| AI-quality / eval / model-risk promotion gate | **Hrz4** `model-quality-gate` | its eval metrics gate promotion (R5); the offline gate mirrors it |
| Observability + immutable WORM prompt/response audit | **Hrz5** `agent-observability` | writes audit events to it (R2); traces spans through it |
| Human-Review & Maker-Checker Console | **Hrz7** human-review console | escalated briefings route to it via `review-kit` (R8) |
| Regulatory Q&A / suitability control checklists | **Rsk1** `compliance-advisory` | consumes it for regulatory compliance checks |

So the guardrail, knowledge base, audit sink, eval platform and review console are
*dependencies*, not features of this repo. Doc3's own `SuitabilityPolicy` and alignment
services are the client-level decision logic, distinct from the platform's runtime controls.

### Where does the client and market data come from?

The client's risk profile / KYC attributes and portfolio holdings come from an internal,
CMEK-encrypted, in-region store (BigQuery on the `gcp` profile; a seeded SQLite store on
`local`). The CIO house views come from the governed Hrz2 knowledge base. Doc3 joins the two
and reasons over them; it is not the system of record for either.

### Can I use this for a non-advisory suitability product?

Yes, that is the point of the ports-and-adapters design. The reusable core (citations,
grounding, the deterministic suitability engine, audit, eval, maker-checker, the human-review
routing) transfers to insurance-product suitability, product-appropriateness checks, and
similar decision-support verticals. You replace the artifact models and prompts and retune the
policy and taxonomy. See [`docs/ADOPTING.md`](../ADOPTING.md) and
[adoption-faq.md](adoption-faq.md).

### How do I see it working?

`make demo` builds cited, suitability-tagged briefings on synthetic data and renders a static,
audit-first HTML view offline; `make demo-server` serves a live presenter-controlled
walkthrough on port 8099. Everything runs on fictional data with no cloud and no API key.
`DEMO.md` documents the offline demo and the managed-GCP path.
