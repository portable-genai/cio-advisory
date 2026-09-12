# variables.tf : The only knobs. Everything else is a concrete in-region value.
#
# General Principle map:
#   P-03 (residency): `region` is SELECTED AT DEPLOY TIME and validated against the
#         residency allowlist (var.allowed_regions) so a caller fails fast rather than
#         deploying to an unvetted, out-of-jurisdiction region. The default is
#         asia-southeast1 (Singapore).
#   P-08 (auditability/retention): `retention_days` is a variable (the WORM bucket lock is
#         irreversible, so retention must be deliberate).
#
# Per the build contract, ONLY project_id and a couple of genuinely per-tenant values
# (org/billing ids, the VPC-SC toggle) are variables. All service identifiers, locations,
# and template names are concrete.

variable "project_id" {
  description = "Target GCP project id (required). Single-tenant, Singapore-resident."
  type        = string
}

variable "allowed_regions" {
  description = <<-EOT
    Residency allowlist: the regions this regulated stack may be deployed to. The region is
    chosen at deploy time (var.region) and validated against this list to FAIL FAST (P-03),
    so an operator cannot accidentally deploy to an unvetted region. Extending this list is
    the deliberate residency review point: do it only after confirming the full managed stack
    (Vertex/Agent Platform, Model Armor, DLP, BigQuery, CMEK, Logging) and your residency
    obligations are satisfied in that region.
  EOT
  type        = list(string)
  default     = ["asia-southeast1"]

  validation {
    condition     = length(var.allowed_regions) > 0
    error_message = "allowed_regions must list at least one residency-approved region."
  }
}

variable "region" {
  description = <<-EOT
    Deployment region, SELECTED AT DEPLOY TIME. Defaults to asia-southeast1 (Singapore) but
    is overridable. Validated against var.allowed_regions so an unapproved region fails fast
    at `terraform plan` rather than deploying data out of jurisdiction (P-03).
  EOT
  type        = string
  default     = "asia-southeast1"

  validation {
    # Cross-variable validation (Terraform >= 1.9). Fails at plan time = setup time.
    condition     = contains(var.allowed_regions, var.region)
    error_message = "region must be one of var.allowed_regions (residency allowlist). Add it there first if that region is approved for this workload (P-03)."
  }
}

variable "zone" {
  description = "Default zone for zonal resources. Must sit inside var.region."
  type        = string
  default     = "asia-southeast1-a"
}

variable "retention_days" {
  description = <<-EOT
    Audit-log retention in days on the cio-advisory-worm bucket. Default ~7 years.

    The 2557-day compliance floor binds whenever worm_locked = true. A stack that declines the
    lock is not keeping a record anyone relies on for seven years and may keep less. The floor
    is conditional on the lock rather than removed, so a LOCKED bucket can never be created with
    a short window.
  EOT
  type        = number
  default     = 2557 # ~7 years; mirrors config/settings.yaml logging.retention_days

  validation {
    condition     = var.retention_days >= 1 && (!var.worm_locked || var.retention_days >= 2557)
    error_message = "retention_days must be at least 1, and at least 2557 (~7 years) whenever worm_locked = true (P-08)."
  }
}

variable "org_id" {
  description = "Organization id : required for Org Policy and Access Context Manager."
  type        = string
}

variable "billing_account" {
  description = "Billing account id (used by Assured Workloads / FinOps tagging)."
  type        = string
  default     = ""
}

variable "access_policy_id" {
  description = <<-EOT
    Existing Access Context Manager policy id (numeric, no prefix) for the org.
    Required when enable_vpc_sc = true; the service perimeter is created under it.
    Create once per org with:
      gcloud access-context-manager policies create \
        --organization=ORG_ID --title="sg-residency"
  EOT
  type        = string
  default     = ""
}

variable "vpc_network_name" {
  description = "Name of the VPC that hosts the private data plane."
  type        = string
  default     = "cio-advisory-vpc"
}

variable "enable_vpc_sc" {
  description = "Create the VPC Service Controls perimeter around the AI/data APIs (P-03)."
  type        = bool
  default     = true
}

variable "worm_locked" {
  type        = bool
  description = <<-EOT
    Lock the cio-advisory-worm audit bucket (P-08).

    #########################################################################
    # WARNING: LOCKING IS IRREVERSIBLE. With true, the bucket and its       #
    # retention window can NEVER be reduced or deleted until every entry    #
    # ages out (retention_days), not even with project-owner rights.        #
    #########################################################################

    NO DEFAULT, and that is the decision. An irreversible control must never arrive because a
    deployment said nothing, so there is no default of true. A fork running this as a system
    of record must not quietly lose the WORM guarantee either, so there is no default of false.
    Every plan names it.

    true is the compliant production posture. false keeps the bucket, its retention and its
    sink, and leaves the bucket destroyable: an evaluation or reference posture, NOT WORM.
    Setting false against a bucket that is ALREADY locked does not unlock it; the API refuses.
    This governs the first apply.
  EOT
}

variable "manage_org_policies" {
  type        = bool
  default     = true
  description = <<-EOT
    Whether THIS stack writes the project's Org Policies (gcp.resourceLocations,
    compute.vmExternalIpAccess, storage.uniformBucketLevelAccess and
    gcp.restrictNonCmekServices).

    True by default, because a fork deploying this app on its own project should inherit the
    residency guardrail rather than have to remember it. Set false where another stack in the
    same project already owns them: two stacks declaring the same project-level policy is a
    last-writer-wins race, and the loser is whichever application needed the wider boundary.

    In a shared project that is not hypothetical. This stack derives its location allowlist from
    its own region and its own house-view store location, so applying it narrows
    gcp.resourceLocations to those two and breaks every sibling that reaches another one, and
    restrictNonCmekServices refuses any sibling's BigQuery or Logging resource that is not
    CMEK-encrypted. Nothing in this stack's plan says so.
  EOT
}

variable "manage_audit_config" {
  type        = bool
  default     = true
  description = <<-EOT
    Whether THIS stack writes the project's data-access audit configuration.

    True by default: data-access logging is what shows who read whose portfolio, and an app
    deployed on its own project should turn it on rather than rely on being told to.

    Set false where another stack in the same project already owns it.
    `google_project_iam_audit_config` is AUTHORITATIVE for the service it names, so a second
    stack declaring `allServices` does not add to the configuration, it replaces it. Terraform
    shows that as a create, not a change, because this stack holds no prior state for a
    resource that is already live.
  EOT
}

variable "model_armor_full_capabilities" {
  type        = bool
  default     = true
  description = <<-EOT
    Whether the guardrail template asks for the malicious-URI filter, which is not served in
    every region.

    True by default, because a deployment should get the whole guardrail unless it has a reason
    not to. asia-southeast1 does not serve it, and Model Armor does not degrade: it refuses the
    template with CAPABILITY_NOT_SUPPORTED, so the stack does not deploy at all. A deployment
    there sets this false, which narrows the guardrail and is a disclosure to make in the
    deployment's posture record rather than a silent downgrade.
  EOT
}

variable "additional_serving_service_accounts" {
  type        = list(string)
  default     = []
  description = <<-EOT
    Service-account emails, other than this stack's own serving identity, that run this
    application's API and therefore need to read its dataset, query its house-view store and
    call its models, DLP templates and guardrail.

    Exists for embedding hosts. A portal that mounts this console same-origin runs the API under
    a runtime identity of the PORTAL's making, which this stack cannot know and the serving
    identity's grants do not cover; without this the deployed app authenticates fine and then
    fails on its first BigQuery read. Empty by default, because an app deployed on its own needs
    none. The host grants its own runtime baseline (logs, traces, metrics); this grants only
    what reaches this application's data and models.
  EOT
  validation {
    condition = alltrue([
      for email in var.additional_serving_service_accounts :
      can(regex("^[a-z0-9-]+@[a-z0-9-]+\\.iam\\.gserviceaccount\\.com$", email))
    ])
    error_message = "each additional_serving_service_accounts entry must be a service-account email."
  }
}

variable "house_views_location" {
  type        = string
  default     = "us"
  description = <<-EOT
    Agent Search location of the house-view data store and its search engine. NOT var.region.

    Agent Search serves `global`, `us` and `eu` and no Cloud region, so a store placed at the
    deploy region cannot be created and a client addressing one reaches a host that does not
    exist. `us` confines the fictional corpus and its index to one named jurisdiction. `global`
    names none, and a project that enforces gcp.resourceLocations refuses it when a document is
    written or searched, not only when the store is created.

    The API reads the same value from CIO_HOUSE_VIEWS_LOCATION (output house_views_api_env), and
    scripts/ingest_house_views.py writes to it. The application's default equals this default,
    and tests/contract/test_house_view_store_location.py fails when the two defaults or the
    allowed values differ.

    Where this stack writes the project's Org Policies (manage_org_policies), this location is
    the second value gcp.resourceLocations admits beside the region's own group, so changing it
    is a residency statement as much as a placement: the policy follows it (org_policy.tf).
  EOT

  validation {
    condition     = contains(["global", "us", "eu"], var.house_views_location)
    error_message = "house_views_location must be one of global, us, eu: the only locations Agent Search serves. A Cloud region such as asia-southeast1 is not one."
  }
}
