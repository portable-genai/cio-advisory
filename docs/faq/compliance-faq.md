# Compliance FAQ

For compliance, MLRO, and model-risk teams assessing the repo's regulatory posture.
Cross-references: [`COMPLIANCE.md`](../../COMPLIANCE.md) (the full principle to control map),
[`SPEC.md`](../../SPEC.md).

### Is this giving financial advice?

No, and it is engineered not to. This is a **decision-support** assistant (P-05): it produces
suitability-checked *talking points* for a relationship manager, never a recommendation to a
client. Every `TalkingPoint` is `is_advice = False`, the synthesis prompt forbids directive
phrasing (`domain/prompts.py`), and every output carries a mandatory non-advice disclaimer.
The `no_advice_safety` eval metric (threshold 0.99) fails the build if any output reads as
advice or the disclaimer is missing. The RM is the human checker and owns any advice given.

### Is this making decisions autonomously?

No. Every `AdvisoryBriefing` sets `requires_human_review = True` (maker-checker, P-06); the
assistant proposes and a qualified human disposes. Points assessed UNSUITABLE are dropped,
never shown as a recommendation, and REVIEW / UNSUITABLE findings *raise* the review bar and
route the briefing to a human, they never auto-execute. Empty retrieval is a hard error, so
the assistant is never ungrounded.

### Where does an escalation actually go?

To the sibling **Hrz7 Human-Review & Maker-Checker Console** (mandatory rule R8). Every
escalated briefing is submitted via the shared `review-kit` client, redact-before-wire:
the `local` profile enqueues to a transactional outbox so the routing path runs offline, and
`gcp`/`platform` submit over S2S to Hrz7's intake (`HUMAN_REVIEW_URL`). See
`ports/review_router.py` and `adapters/{local,platform,onprem}/review_router.py`. The
maker-checker escalation is a routed action, not a boolean left on the record.

### How is client PII handled?

Redact-before-everything (P-04): `redaction.redact(...)` runs first in the pipeline
(`domain/advisory_service.py`) before any model, index, registry or audit call, and audit
records store already-redacted text. National-identifier detection is **jurisdiction-driven**
and comes from the shared, versioned `pii-kit` package (SG / HK / JP / AU rows, their
checksum validators and RE2-safe forms), selected by `pii.jurisdictions` (or
`CIO_PII_JURISDICTIONS`) so a non-Singapore deployment scrubs, and gates on, its own
identifiers. The local regex redactor, the GCP DLP custom info types, and the eval leak check
all read that one source, so there is no drift between them. The runtime guardrail / DLP
gateway itself is the sibling **Hrz1** service; this repo consumes it rather than
re-implementing it.

### How is the work auditable / reproducible?

Every briefing path writes an immutable, already-redacted WORM `AuditEvent` with the decision
and its citation set (P-07). Every talking point carries its supporting `Citation`s (P-10).
The consequential logic, the suitability verdicts and the portfolio-alignment math, is
**deterministic and replayable** (pure stdlib, unit-tested), so an auditor can recompute
every verdict from the same inputs without the model. The enterprise WORM audit system is
**Hrz5**; the in-repo hash-chained store is the offline/local stand-in (see
[security-faq.md](security-faq.md) for its exact tamper-evidence limits).

### What is the model-risk story?

An offline eval gate (`eval/run_eval.py`) scores groundedness, suitability accuracy, citation
accuracy, and the `no_advice_safety` / `pii_safety` safety metrics (each threshold 0.99)
against a fictional golden set, failing the build below threshold (P-08). It runs in CI on
`CIO_PROFILE=onprem` with no org secrets. The enterprise judged pre-promotion gate and model
documentation / red-team harness are the sibling **Hrz4** system (rule R5); this repo's gate
mirrors its thresholds so merges are guarded locally. A fork must rebuild the golden set for
its own vertical, or the gate measures the wrong thing.

### Which regulators does this map to?

`COMPLIANCE.md` maps the internal P-01..P-12 / R1..R8 controls to concrete code, with the MAS
(Singapore) posture as the built reference (`asia-southeast1` residency, the suitability and
non-advice framing). To extend to FCA / MAS FAA / HKMA / APRA suitability regimes, own the
`suitability.concentration_limit` and the risk-appetite / complex-asset gates in
`domain/suitability_policy.py` with local counsel and re-review. At scale, the sibling **Rsk1
compliance assistant** answers the regulatory-checklist questions and a control-mapping
toolkit maintains the crosswalks; a large estate should integrate them rather than
hand-maintain the mapping.

### Is data residency enforced?

Yes, at deploy time: a single in-country region (default `asia-southeast1` / Singapore),
validated to fail fast, with regional endpoints, a `gcp.resourceLocations` Org Policy
allowlist, CMEK bound per data-bearing service, and a VPC-SC perimeter (P-03, P-09). The
residency-violation CI gate is the sibling **Rsk3** `architecture-validator`
(`domain/residency/`); the exit / concentration-risk plan is **Rgc9**
`operational-resilience-mapping` (`domain/concentration_exit/`). This repo enforces residency in
its own infra and is one of the systems those tools reason about.

### Can we run it against real client data today?

Not without your own legal, security, and model-risk sign-off. Every shipped client,
portfolio and house-view fixture uses obviously-fictional ids (`client-000042`,
`client-000077`), and the docs state throughout that this is a reference build. The adoption
checklist ([`docs/ADOPTING.md`](../ADOPTING.md) §4-§6) lists the steps, replace the fixtures
and seeded corpus, own the suitability policy, wire your IdP, rebuild the eval golden set,
that must precede any live-data use.
