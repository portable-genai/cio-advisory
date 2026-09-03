# Doc3 Compliance Map

How the catalog's general principles (P-01..P-12) and mandatory rules (R1..R6, R8) map to
concrete controls in **this** repo. Doc3 stresses the suitability obligation and the
**advice / decision-support boundary**: the assistant never advises; the relationship
manager (RM) is the human checker.

Principles marked **n/a** genuinely do not apply to Doc3 and say why.

## General principles

| Principle | Status | Where it lives in Doc3 |
|---|---|---|
| **P-01** managed-first, minimal surface | Met | `[gcp]` extra is the only place SDKs live; `infra/terraform/apis.tf` enables exactly the services SPEC §3 names, nothing speculative. |
| **P-02** no vendor lock-in (ports and adapters) | **Emphasised** | Pure `domain/`; `ports/` Protocols; four adapter families (`gcp` / `local` / `platform` / `onprem`); one `CIO_PROFILE` switch. The `local` family is a WORKING, SDK-free, off-cloud proof: the whole advisory pipeline runs end to end with no Google Cloud package imported (`CIO_PROFILE=local cio-advisory briefing client-000042`). `tests/contract/test_port_parity.py` proves both the `local` (working) and `onprem` (fail-fast) families are interface-parity. |
| **P-03** data residency (in-country) | Met | Region defaults to `asia-southeast1` in `config/settings.yaml` and is chosen at deploy time, validated in `infra/terraform/variables.tf` against the `allowed_regions` residency allowlist (extending that list is the review point); `org_policy.tf` (`gcp.resourceLocations`) and `vpc_sc.tf` enforce it; BigQuery dataset and DLP/Model Armor templates are regional. |
| **P-04** data minimisation / redact PII | **Emphasised** | `redaction.redact(...)` runs first in the pipeline (`domain/advisory_service.py`); DLP `deidentifyContent` + a custom SG NRIC/FIN detector (`adapters/gcp/dlp_redaction.py`, `infra/terraform/dlp.tf`); audit records store already-redacted text; trace content capture OFF. |
| **P-05** private networking | Met | `org_policy.tf` disables VM external IPs and enforces uniform bucket access; `vpc_sc.tf` perimeter around the data plane. |
| **P-06** maker-checker (human in the loop) | **Emphasised** | `CioReviewPolicy` makes every `AdvisoryBriefing` `requires_human_review = True`; REVIEW/UNSUITABLE points escalate the audit decision. The escalation is ROUTED to the Hrz7 maker-checker console (rule R8), not left as a boolean (`ports/review_router.py`, `adapters/*/review_router.py`). The RM is the checker; the assistant never advises (`is_advice = False`, mandatory non-advice disclaimer). |
| **P-07** audit everything | **Emphasised** | Every briefing path writes an `AuditEvent` to the WORM sink (`AuditSinkPort`), with citations and a redacted prompt/response; `infra/terraform/logging_worm.tf` locks the bucket (retention 2557 days) and enables DATA_READ audit logs. |
| **P-08** auditability / model-risk gate | Met | `eval/run_eval.py` is the offline promotion gate (groundedness, suitability accuracy, citation accuracy, no-advice safety); the hosted GitHub Actions check runs it; Hrz4 is the judged pre-promotion gate (R5). |
| **P-09** CMEK does not cascade | Met | One regional key in `infra/terraform/kms.tf` with an explicit binding per data-bearing service (BigQuery, Agent Search, Agent Runtime, Logging); `org_policy.tf` `restrictNonCmekServices` backstop. |
| **P-10** least-privilege identities | Met | `infra/terraform/iam.tf` + `agent_runtime.tf` give the app and the runtime distinct service accounts with only the roles each needs (read-only on the portfolio store from serving). |
| **P-11** governed discovery / registration | Met | A2A AgentCard at `/.well-known/agent-card.json` (`agent/agent_card.py`); registered with Hrz3 via `adapters/platform/remote_registry.py`; governed MCP tool catalog (`adapters/gcp/mcp_tool_catalog.py`). |
| **P-12** reversibility | Met | The on-prem adapter family is the demonstrable migration target (`docs/onprem-migration.md` documents the port), and the `local` family proves the domain already runs entirely off-cloud (SQLite FTS5, deterministic LLM, regex DLP, append-only audit). The contract test guarantees the interface holds across both. |

## Mandatory rules

| Rule | Status | How Doc3 satisfies it |
|---|---|---|
| **R1** full Hrz1 safety pipeline (PII vertical) | Met | Doc3 handles customer PII / financial data, so the full redact -> guardrail INPUT -> ... -> guardrail OUTPUT -> audit pipeline runs on every request (`domain/advisory_service.py`), backed by Hrz1 (`GuardrailPort` + `PIIRedactionPort`, Model Armor + DLP, or the Hrz1 gateway on the platform profile). |
| **R2** audit to Hrz5 | Met | `AuditSinkPort` -> Cloud Logging WORM (gcp) or the Hrz5 `agent-observability` service (`adapters/platform/remote_audit.py`). |
| **R3** governed RAG via Hrz2 | Met | House-view retrieval is via the governed Hrz2 knowledge base (`adapters/platform/remote_house_views.py` -> `/v1/search`); Doc3 builds no separate retrieval backend. |
| **R4** register in Hrz3 | Met | `adapters/platform/remote_registry.py` registers the AgentCard with Hrz3; the card advertises the three Doc3 skills. |
| **R5** pass Hrz4 before promotion | Met | `EvaluationGatePort` -> Hrz4 (`adapters/platform/remote_eval_gate.py`) plus the in-repo offline gate (`eval/run_eval.py`) as the merge guard. |
| **R6** validated by Rsk3 at intake | Met (external) | Doc3 is registered for Rsk3 architecture-validation at intake; the dotted-path build contract in `config/settings.yaml` is what Rsk3 reads. |
| **R8** route `requires_human_review` to Hrz7 | Met | Every escalated briefing is submitted to the Hrz7 Human-Review & Maker-Checker Console via the shared `review-kit` client (redact-before-wire); `local` enqueues to a transactional outbox so the routing path runs offline, `gcp`/`platform` submit over S2S to Hrz7's service intake (`HUMAN_REVIEW_URL`). `ports/review_router.py`, `adapters/{local,platform,onprem}/review_router.py`, `adapters/_review_payload.py`. |

## The advice / decision-support boundary (Doc3-specific)

This is the control that matters most for Doc3.

- **Never advises.** Talking points are `is_advice = False`; the synthesis prompt forbids
  directive phrasing (`domain/prompts.py`); the `no_advice_safety` eval metric (threshold
  0.99) fails the build if any output reads as advice or the disclaimer is missing.
- **Suitability-tagged.** Every theme carries a `SuitabilityAssessment`; UNSUITABLE points
  are dropped, REVIEW points are flagged. The `SuitabilityPolicy` is the regulatory heart
  and is the most heavily unit-tested module.
- **Maker-checker.** Every briefing requires human review (P-06); the RM signs off any
  advice to the client.
- **Synthetic data only.** The shipped client/portfolio data is fictional. Loading live
  client data requires sign-off; the portfolio store is internal, CMEK-encrypted, and
  inside the residency perimeter.

## Adopter-owned regulator crosswalk

This appendix is intentionally adopter-owned. The adopting bank's compliance function
must determine applicability, nominate owners, and link approved evidence before production.

| Reference topic | Candidate control evidence | Applicability | Adopter owner | Approved evidence |
|---|---|---|---|---|
| MAS fair dealing and suitability | deterministic suitability policy; decision-support disclaimer | To assess | To assign | To link |
| MAS TRM model and change controls | P-06, P-08; maker-checker and eval gate | To assess | To assign | To link |
| MAS data protection and residency | P-04, P-05; redaction, CMEK, perimeter | To assess | To assign | To link |
