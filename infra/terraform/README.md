# `cio-advisory` CIO Advisory Assistant : Terraform (Singapore-resident, sovereign deploy)

This module provisions the full **Singapore-resident** managed stack for the `cio-advisory` CIO
Advisory Assistant. Every resource takes its location from `var.region`, which is chosen
at deploy time and validated against the `allowed_regions` residency allowlist (default
`["asia-southeast1"]`), with one exception the service forces: the house-view store sits at
`house_views_location` (default `us`), because Agent Search serves only `global`, `us` and `eu`
(see [The house-view store](#the-house-view-store)). Only `project_id` and a few genuinely
per-tenant values are variables.

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

terraform init -input=false -backend-config=bucket=<state-bucket> -backend-config=prefix=cio-advisory
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

## State

`providers.tf` declares a partial `backend "gcs" {}`. The bucket and the prefix are init inputs,
never code: `<state-bucket>` is the deployment's state bucket, which every other deployed stack
shares under its own prefix, and this stack's prefix is `cio-advisory`. Local state for a stack
that owns a KMS key, the BigQuery dataset and the house-view store is the deployment's only
record of them, sitting on whichever laptop ran the apply, so a named deployment does not keep
it. The offline proof never touches the bucket: `make tf-check` runs
`terraform init -backend=false` before `validate`, `fmt -check` and `test`.

**Migrate existing local state once. Never re-create it.** An installation applied before the
backend was declared holds its state in a gitignored `terraform.tfstate` in this directory,
recording the `wealth_portfolio` dataset and its tables, the KMS key ring and key, and the
enabled services. From the directory holding that file, with credentials:

```bash
terraform init -migrate-state -backend-config=bucket=<state-bucket> -backend-config=prefix=cio-advisory
terraform plan   # expect no creates for the dataset, its tables or the key ring
```

Answer `yes` when init offers to copy the existing state into the bucket. Starting from an empty
prefix instead plans the dataset and the key ring as new, and both creates fail because both
already exist. Keep the local file until the migrated plan shows none of those creates.

## The house-view store

`house_views.tf` creates the Agent Search data store `cio-house-views` and the engine
`cio-advisory-engine` the standalone `gcp` profile searches. Agent Search has no Cloud-region
location, only `global`, `us` and `eu`, so the store cannot sit in `var.region`:
`house_views_location` places it, validated to those three, default `us` (one named
jurisdiction; `global` names none and a residency Org Policy refuses it when a document is
written). This is the stack's one disclosed residency exception: the fictional CIO corpus and
its index live there, the client book stays in the region.

**The API must read the same location.** `config/settings.yaml` reads it from
`CIO_HOUSE_VIEWS_LOCATION`, default `us`; the output `house_views_api_env` is exactly that
variable and value, to copy into the API's environment (the portal's `api_env` for an embedded
deployment). `tests/contract/test_house_view_store_location.py` fails the build when the two
defaults, the allowed values or the store and engine ids drift apart, and `make tf-check`
refuses a Cloud region and proves the engine follows the store.

**It is created empty.** `scripts/ingest_house_views.py` fills it through the API's own adapter
(`docs/runbook.md`, "The house-view store"): `make ingest-house-views PROJECT=<id>
TENANT=<tenant>`, where the tenant is the one the deployment's identity adapter resolves.

**CMEK.** The store carries no customer-managed key. Agent Search accepts only a `us` or `eu`
key registered to the location before the store exists, on Enterprise edition; the regional key
in `kms.tf` can never be one and the engine is Standard tier, so the store uses Google-managed
encryption and `org_policy.tf` leaves `discoveryengine.googleapis.com` out of the services
`restrictNonCmekServices` denies.

**Org Policies.** Where this stack writes them (`manage_org_policies = true`),
`gcp.resourceLocations` admits exactly two values: `in:<region>-locations` and the store's
location group (`in:us-locations` by default, `global` as a literal). In a shared project the
owner's policy must admit the store's location or the apply is refused.

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
| House-view store location | `house_views_location` | `us` (the default), and the owner's `gcp.resourceLocations` must admit `in:us-locations` | Agent Search serves no region; the API reads the same value from `CIO_HOUSE_VIEWS_LOCATION` |

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
Add `CIO_HOUSE_VIEWS_LOCATION` from `terraform output house_views_api_env` whenever
`house_views_location` is not the default, and load the house views under the same tenant the
domain map resolves.

`make tf-check` proves every decline above offline, with mock providers and no credentials.

## Warnings

- **WORM lock is irreversible.** `logging_worm.tf` locks the audit log bucket when
  `worm_locked = true`, and the variable has no default, so every deployment names it. Once
  applied true you cannot reduce retention or delete the bucket for the retention window
  (`retention_days`, default 2557 days, roughly 7 years), not even as project owner.
- **The house-view store is outside the region.** Agent Search serves only `global`, `us` and
  `eu`; the store sits at `house_views_location` (default `us`) and the API must read the same
  value. See [The house-view store](#the-house-view-store).
- **CMEK does not cascade.** The data-bearing services that accept a regional key (BigQuery,
  Agent Runtime, Logging) get an explicit binding to the single regional CMEK in `kms.tf`.
  Agent Search does not accept one, so the house-view store is Google-managed and is the one
  service `org_policy.tf`'s `restrictNonCmekServices` backstop does not cover.
- **Synthetic data only by default.** The portfolio/profile tables created here are empty;
  the sample client data shipped with this repo is fictional. Do not load live client data
  without sign-off (see `COMPLIANCE.md`).
