# Adopting this repo as your base

This repository is a **common base** that BFSI institutions (and other regulated industries)
fork to build their own grounded, suitability-checked **decision-support** agents: private-
bank advisory, insurance suitability, product-appropriateness checks, portfolio-alignment
copilots. It ships a reusable hexagonal core (a pure-stdlib domain, typed ports, swappable
adapter profiles, a green offline gate) plus a fully worked CIO-advisory / suitability
vertical you can keep, replace, or learn from.

This is decision-support, never financial advice: adopt it that way. Every output is
suitability-tagged, carries a non-advice disclaimer, and is maker-checker gated; the human
checker (an RM, adviser, or reviewer) owns any advice given to the client.

This guide is the step-by-step for making it yours. It has two halves: a **mechanical
rebrand** (one script) and the **human decisions** the script cannot make for you.

> Related reading: [`ARCHITECTURE.md`](../ARCHITECTURE.md) (the hexagon and profiles),
> [`CONTRIBUTING.md`](../CONTRIBUTING.md) (adding a port / sub-service), the
> [`faq/`](faq/) directory.

---

## 1. What you keep vs what you rewrite

The domain speaks only to ports, so the reusable machinery is separable from the vertical:

| Layer | Where | For a new vertical |
|---|---|---|
| **Neutral machinery** | `domain/models.py` (the vertical-neutral types: `Citation`, `GuardrailVerdict`, `RedactionResult`, `AuditEvent`, `EvalReport`), `domain/serialization.py` (`to_jsonable`), `domain/errors.py`, the generic ports (LLM, guardrail, redaction, audit, tracer, eval, identity, review-router) | keep untouched |
| **Policy** (your numbers) | `suitability.concentration_limit` in `config/settings.yaml` and the risk-appetite / complex-asset gates in `domain/suitability_policy.py` | change by config and policy review, not by rewiring the pipeline |
| **Vertical** (advisory artifacts) | the advisory models in `domain/models.py` (`AdvisoryBriefing`, `TalkingPoint`, `SuitabilityAssessment`), the narrating service (`domain/talking_points_service.py`), `domain/prompts.py`, the local fixtures, the eval golden set, the UI advisory views | rewrite for your artifacts |

If your product is another *suitability / decision-support* vertical, most of the neutral
machinery and the deterministic suitability engine transfer directly; you replace the
artifact models and the prompts, and retune the policy and taxonomy.

## 2. Core-vs-adopter-owned files (so upstream merges stay mechanical)

Upstream keeps evolving these; avoid diverging from them so you can pull fixes cleanly:

- **Upstream-owned** (take our changes): the neutral types in `domain/models.py`, `ports/`,
  `tests/contract/`, the eval harness mechanics (`eval/run_eval.py`), CI workflows, and the
  hexagon wiring (`config.py` `Container`).
- **Adopter-owned** (yours; expect to edit): `config/settings.yaml` *values*, the local
  fixtures and seeded house-view corpus, `adapters/onprem/*`, UI theming/branding, the
  golden eval dataset, `COMPLIANCE.md` jurisdiction rows.

Track upstream via git tags; rebase your adopter-owned
changes onto each release rather than merging `main` continuously.

## 3. The mechanical rebrand (one script)

`scripts/rename_fork.py` rewrites the package name (`cio_advisory`), CLI entry point
(`cio-advisory`), `CIO_` env prefix, and resource ids across the tree in one pass. In this
repo the CLI name, the resource stem and the distribution name are the same string; the
distribution and the console script are rewritten through their own declarations, so
`--dist`, `--cli` and `--resource` may differ, and matching values are the common case.
Preview first, then apply:

```bash
# Preview (writes nothing):
python scripts/rename_fork.py --package acme_advisory --cli acme-advisory \
    --env-prefix ACME --resource acme-advisory --dry-run

# Apply:
python scripts/rename_fork.py --package acme_advisory --cli acme-advisory \
    --env-prefix ACME --resource acme-advisory --yes

# Then recreate the environment (the distribution name changed) and prove it is green:
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
make lint test eval
```

Add `--include-docs` to sweep Markdown prose too. The script deliberately does NOT touch the
human decisions below.

## 4. The human decisions (the script can't make these)

1. **Region / residency.** Set `CIO_REGION` (now `<PREFIX>_REGION`) and the Terraform
   `region`/`tfvars` to your in-country region. The build defaults to `asia-southeast1`
   (MAS / Singapore). See [`docs/runbook.md`](runbook.md).
2. **Identity / IdP.** This repo does not own a web login flow. Identity resolves server-side
   per profile: `gcp`/`platform` verify the IAP-injected signed assertion, `local` uses
   seeded dev personas (offline only, no IdP), and `onprem` is a client-IdP placeholder you
   implement. Wire your IdP into the `onprem` identity adapter and configure IAP on the
   deployed service. See [`docs/embedding-and-identity.md`](embedding-and-identity.md).
3. **PII / jurisdiction pack.** Set `pii.jurisdictions` (and `CIO_PII_JURISDICTIONS` for the
   eval gate) so redaction and the `pii_safety` metric detect YOUR national identifiers, not
   just the shipped SG / HK / JP / AU set. The rows come from the shared `pii-kit` package;
   add a jurisdiction there if yours is not yet listed. An unknown code degrades to universal
   email / phone rather than raising.
4. **Suitability policy.** Own the numbers your compliance function controls: the
   `suitability.concentration_limit` in `config/settings.yaml` and the risk-appetite /
   complex-asset / knowledge-rank gates in `domain/suitability_policy.py`. The defaults are a
   reference, not your policy; retune and re-review them, and pin the behavior with a test.
5. **Reference data is fictional.** Every shipped client, portfolio, and house-view fixture
   uses obviously-fake ids (`client-000042`, `client-000077`). Swap the fixtures and the
   seeded corpus for your own synthetic data. **Do not run against live client data without
   your own legal, security and model-risk sign-off.**
6. **Eval golden set.** Rebuild `eval/datasets/` and the rubrics for your vertical: a fork
   inherits a green gate that measures the WRONG thing until you do. The gate structure and
   the `no_advice_safety` / `pii_safety` metrics are generic; the golden cases are yours.
7. **Deployment posture.** Review the Dockerfile (digest-pinned base, non-root, port 8091),
   `infra/terraform/` (Org Policy, CMEK, VPC-SC, WORM logging), and the loopback-by-default
   binding before you expose anything.

## 5. Do not duplicate the platform

This repo is one system in a catalog of composable GRC systems. Several concerns it
*touches* are owned by sibling platform services, and you should integrate rather than
rebuild them (see [`docs/faq/features-faq.md`](faq/features-faq.md) for the full map): the
guardrail gateway (`agent-guardrail-gateway`), the governed knowledge base that serves the CIO house views
(`enterprise-knowledge-base`), the agent registry (`agent-registry`), the AI-quality / eval gate (`model-quality-gate`), observability + WORM
audit (`agent-observability`), the Human-Review & Maker-Checker Console that escalations route to (`human-review-console`), and
the compliance assistant (`compliance-advisory`). The `platform` profile's adapters are already thin HTTP
clients to those services.

## 6. Adoption checklist

- [ ] Ran `scripts/rename_fork.py`, recreated the venv, `make lint test eval` green.
- [ ] Set region + Terraform tfvars to your in-country region.
- [ ] Wired your IdP into the `onprem` identity adapter and configured IAP on the service.
- [ ] Set `pii.jurisdictions` + added a pattern pack if needed; `pii_safety` exercises your ids.
- [ ] Owned the suitability numbers with your compliance function and pinned them with a test.
- [ ] Replaced every synthetic fixture and the seeded house-view corpus.
- [ ] Rebuilt the eval golden set + rubrics for your vertical.
- [ ] Reviewed the deploy posture (Dockerfile, Terraform, bind address).
- [ ] Decided which sibling platform services you integrate vs stub.
- [ ] Recorded your baseline upstream tag so you can take future fixes.
