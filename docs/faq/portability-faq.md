# Portability FAQ

For architecture, cloud-governance, and exit-planning teams. The claim this repo makes is
"no vendor lock-in, demonstrably" (General Principle P-02 / P-12), and it is designed to be
*shown*, not asserted. Cross-references: [`ARCHITECTURE.md`](../../ARCHITECTURE.md),
[`docs/onprem-migration.md`](../onprem-migration.md), [`DEMO.md`](../../DEMO.md).

### What does "portable" actually mean here?

The whole stack migrates by a one-line profile change with no domain edits. The pure-domain
core speaks only to `typing.Protocol` **ports**; four **adapter families** implement them,
and `config/settings.yaml` binds one adapter per port per profile. Nothing in
`domain/` changes across profiles, which is the point: `where` the assistant runs is a
configuration choice, not a rewrite.

### How does the profile switch work?

Setting `CIO_PROFILE` (or `profile:` in the settings) rebinds the entire stack:

- `local`: a WORKING offline stack (SQLite FTS5 over the CIO house views, a deterministic
  schema-driven LLM, a heuristic guardrail, regex DLP, a hash-chained append-only audit
  from the shared commons). No Google Cloud SDK. The default for dev/test/CI.
- `gcp`: real managed services (BigQuery portfolios, Agent Search / File Search house
  views, Gemini, Model Armor, DLP, Cloud Logging WORM, Cloud Trace, Gen AI Evals, Agent
  Runtime).
- `platform`: thin HTTP clients delegating to the sibling horizontal-platform and
  de-risking services.
- `onprem`: fail-fast placeholders that still satisfy every Protocol (the sovereign-exit
  target); primary commands exit non-zero by design until the migration is done.

The contract test (`tests/contract/test_port_parity.py`) proves both the `local` (working)
and `onprem` (fail-fast) families construct and satisfy all **16** ports with no cloud SDK
installed. `tests/contract/test_behavioral_parity.py` goes further and asserts
`local == platform` on redaction / guardrail / audit / house_view for one canonical request
(via respx), so the no-lock-in claim is enforced by CI, not just documented.

### How do we get our data out?

Every artifact serializes through `domain/serialization.py` (`to_jsonable`) into open,
documented JSON: the `AdvisoryBriefing`, its `TalkingPoint`s and `SuitabilityAssessment`s,
and each `AuditEvent`. The audit trail is a hash chain, so an export re-verifies line by
line rather than trusting a vendor blob. The exit story for the record set is "copy the
JSON", not "migrate a product".

### Is on-prem / sovereign deployment real or aspirational?

The `onprem` adapters are deliberate fail-fast placeholders (they raise before doing cloud
work) that nonetheless satisfy every Protocol and construct with a single `Settings` arg, so
the *interface contract* for a sovereign migration is proven and enforced by CI today. The
actual on-prem implementations are the migration work, scoped in
[`docs/onprem-migration.md`](../onprem-migration.md). This repo is not the sovereign-exit
*planner* (that is the sibling `operational-resilience-mapping`, module
`domain/concentration_exit/`: APRA CPS 230, MAS / HKMA outsourcing); this repo is one of the
systems whose exit that planner reasons about.

### Does residency compromise portability?

No. Residency is a deploy-time pin (the region, an Org Policy resource-location allowlist,
CMEK, VPC-SC); portability is the ability to change *where* the stack runs by configuration.
They are orthogonal. The region defaults to `asia-southeast1` (Singapore) and is validated to
fail fast, and a second region or enterprise is a tfvars change, not a fork. Residency
enforcement overlaps with the sibling `architecture-validator` (`domain/residency/`,
a CI gate for region violations), which a fork should run rather than re-implement.

### Does the assistant lock me into Google's agent stack?

No. The ADK root agent and its grounding sub-agent are `gcp`-profile adapters behind the
`AgentRuntimePort`, and they are imported lazily, so importing the package never pulls in the
Google SDK. The A2A AgentCard is served from a plain FastAPI route
(`/.well-known/agent-card.json`), and the `local` profile answers the same advisory pipeline
end to end with no ADK at all. The agent framework is a swappable adapter, not the spine.

### What is NOT yet portable?

The managed, regional CMEK-encrypted stores for the `gcp` profile (BigQuery portfolios,
Agent Runtime sessions / memory) are managed-service bindings; the `local` in-process stores
and the `onprem` placeholders prove interface parity for them, but a live sovereign store is
migration work. Everything in the one-shot advisory pipeline is exercised across `local` and
`gcp` today.
