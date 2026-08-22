# Doc3 CIO Advisory Assistant : Terraform (Singapore-resident, sovereign deploy)

This module provisions the full **Singapore-resident** managed stack for the Doc3 CIO
Advisory Assistant. Every resource takes its location from `var.region`, which is chosen
at deploy time and validated against the `allowed_regions` residency allowlist (default
`["asia-southeast1"]`); only `project_id` and a few genuinely per-tenant values are variables.

It maps directly to the pinned stack in `SPEC.md §3`:

| Concern | Resource(s) |
|---|---|
| House-view retrieval (Agent Search / File Search) | enabled in `apis.tf`; store created via SDK, governed KB is Hrz2 |
| Reasoning/Triage models + Runtime | `agent_runtime.tf` (engine deployed via SDK) |
| Guardrail (Model Armor) | `model_armor.tf` |
| PII redaction (DLP) | `dlp.tf` |
| WORM audit (locked Cloud Logging bucket) | `logging_worm.tf` |
| Portfolio + profile store (BigQuery, CMEK) | `bigquery.tf` |
| Tracing (Cloud Trace) | enabled in `apis.tf`; spans from the app |
| CMEK | `kms.tf` |
| Residency controls | `org_policy.tf`, `vpc_sc.tf` |
| Least-privilege identities | `iam.tf`, `agent_runtime.tf` |

The governed CIO house-view knowledge base itself (Hrz2 Enterprise KB) is provisioned by the
Hrz2 repo, not here: Doc3 retrieves from it over HTTP (`/v1/search`). This module only
provisions the standalone File Search store enablement plus Doc3's own data plane.

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

## Warnings

- **WORM lock is irreversible.** `logging_worm.tf` sets `locked = true` on the audit log
  bucket. Once applied you cannot reduce retention or delete the bucket for the retention
  window (`retention_days`, default 2557 days, roughly 7 years), not even as project owner.
- **CMEK does not cascade.** All data-bearing services (BigQuery, Agent Search, Agent
  Runtime, Logging) get an explicit binding to the single regional CMEK in `kms.tf`.
  `org_policy.tf` adds `restrictNonCmekServices` as a backstop.
- **Synthetic data only by default.** The portfolio/profile tables created here are empty;
  the sample client data shipped with this repo is fictional. Do not load live client data
  without sign-off (see `COMPLIANCE.md`).
