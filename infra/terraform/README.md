# `cio-advisory` CIO Advisory Assistant : Terraform (Singapore-resident, sovereign deploy)

This module provisions the full **Singapore-resident** managed stack for the `cio-advisory` CIO
Advisory Assistant. Every resource takes its location from `var.region`, which is chosen
at deploy time and validated against the `allowed_regions` residency allowlist (default
`["asia-southeast1"]`); only `project_id` and a few genuinely per-tenant values are variables.

It maps directly to the pinned stack in `SPEC.md §3`:

| Concern | Resource(s) |
|---|---|
| House-view retrieval (Agent Search) | `house_views.tf` for the standalone `gcp` profile; the `platform` profile delegates to `enterprise-knowledge-base` |
| Reasoning/Triage models + Runtime | `agent_runtime.tf` (engine deployed via SDK) |
| Guardrail (Model Armor) | `model_armor.tf` |
| PII redaction (DLP) | `dlp.tf` |
| Audit log bucket (WORM when `worm_locked = true`) | `logging_worm.tf` |
| Portfolio + profile store (BigQuery, CMEK) | `bigquery.tf` |
| Tracing (Cloud Trace) | enabled in `apis.tf`; spans from the app |
| CMEK | `kms.tf` |
| Residency controls | `org_policy.tf`, `vpc_sc.tf` |
| Least-privilege identities | `iam.tf`, `agent_runtime.tf` |

The governed CIO house-view knowledge base itself (`enterprise-knowledge-base`) is provisioned by the
`enterprise-knowledge-base` repo, not here: `cio-advisory` retrieves from it over HTTP (`/v1/search`). This module
provisions the standalone `gcp` profile's own house-view store (`house_views.tf`) plus `cio-advisory`'s own data plane.

## Prerequisites

1. **Terraform** >= 1.9 and the **Google** + **google-beta** providers `~> 6.0`.
2. A **GCP project** with billing linked, and an **Organization** (Org Policy and VPC
   Service Controls are org-scoped).
3. An **Access Context Manager policy** for the org (only if `enable_vpc_sc = true`):
   ```bash
   gcloud access-context-manager policies create \
     --organization=ORG_ID --title="sg-residency"
   ```
   Pass its numeric id as `access_policy_id`.

## Apply

```bash
cp terraform.tfvars.example terraform.tfvars   # then edit ids; region defaults to asia-southeast1

terraform init
terraform plan
terraform apply
```

Recommended **two-phase** apply when using VPC Service Controls:

```bash
terraform apply -var='enable_vpc_sc=false'   # 1) build resources
# 2) add your operator/CI identity to a VPC-SC access level
terraform apply -var='enable_vpc_sc=true'    # 3) enforce the perimeter
```

After apply, deploy the Agent Runtime engine out-of-band (it has no first-class Terraform
resource) and wire the outputs into `config/settings.yaml`:

```bash
terraform output    # copy kms_key, portfolio_dataset, templates, service accounts...
```

## Deploying into a shared project under `journey-portal`

The portal creates the `journey-cio-advisory-api` and `journey-cio-advisory-ui` Cloud Run services
from digest-pinned images; this stack is the support stack beside them and runs no service of its
own. In a project where another stack already owns the project-level controls, decline them by
variable:

| Control | Variable | Shared-project value | Why |
|---|---|---|---|
| Org Policies (`gcp.resourceLocations` and three hardening constraints) | `manage_org_policies` | `false` | One value per constraint per project, and this stack's strictest form would narrow a sibling's |
| Data-access audit config | `manage_audit_config` | `false` | Authoritative per service: applying it replaces the owner's configuration |
| VPC-SC perimeter | `enable_vpc_sc` | `false` | A second regular perimeter would enforce where the owner observes |
| Model Armor malicious-URI filter | `model_armor_full_capabilities` | `false` in `asia-southeast1` | The region does not serve it and refuses the whole template |
| WORM lock on the audit bucket | `worm_locked` (no default) | a deliberate `true` or `false` | Irreversible when true |

`additional_serving_service_accounts` names the portal's API runtime identity, which the portal
mints on its own apply. Apply in two passes: this stack with the list empty, then the portal, then
this stack again with the identity filled in. Skipping the second pass yields an API that is READY
and refused on its first BigQuery read. The identity gets this dataset, not every dataset in the
project, and nothing the portal already grants it.

**Images.** `Dockerfile` builds the API (port 8091). `ui/Dockerfile` builds the console (port 3000)
with `NEXT_PUBLIC_BASE_PATH=/apps/cio-advisory` and `NEXT_PUBLIC_API_BASE=/apps/cio-advisory/api`
as build arguments, because Next.js inlines both at build time.

**The API's identity inputs.** `CIO_PROFILE=gcp`, `CIO_IAP_AUDIENCE`, `CIO_IAP_TENANT_DOMAINS_JSON`
mapping each sign-in domain to the tenant the client book was loaded under, and
`CIO_IAP_GROUPS_JSON` granting an advisory role such as `group:cio-analyst`. Without the two maps
every verified user resolves to their own domain, holds no role, and is refused every client.

`make tf-check` proves every decline above offline, with mock providers and no credentials.

## Warnings

- **WORM lock is irreversible.** `logging_worm.tf` locks the audit log bucket when
  `worm_locked = true`, and the variable has no default, so every deployment names it. Once
  applied true you cannot reduce retention or delete the bucket for the retention window
  (`retention_days`, default 2557 days, roughly 7 years), not even as project owner.
- **The house-view store has no deployable location yet.** Agent Search serves only `global`,
  `us` and `eu`, and `house_views.tf` places the store in `var.region`, which it does not serve.
  An apply of the data store and its search engine fails until a location is chosen.
- **CMEK does not cascade.** All data-bearing services (BigQuery, Agent Search, Agent
  Runtime, Logging) get an explicit binding to the single regional CMEK in `kms.tf`.
  `org_policy.tf` adds `restrictNonCmekServices` as a backstop.
- **Synthetic data only by default.** The portfolio/profile tables created here are empty;
  the sample client data shipped with this repo is fictional. Do not load live client data
  without sign-off (see `COMPLIANCE.md`).
