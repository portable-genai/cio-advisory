# apis.tf : Enable exactly the managed services B3 depends on.
#
# General Principle map:
#   P-01 (managed-first / minimal surface): only the services the pinned stack (SPEC §3)
#         actually uses are enabled : nothing speculative.
#   P-03 (residency): enabling these APIs is a prerequisite for the regional, CMEK-protected
#         resources defined in the sibling files.
#
# disable_on_destroy = false so a `terraform destroy` of this stack does not yank platform
# APIs out from under other workloads in a shared project.

locals {
  required_services = [
    "aiplatform.googleapis.com",           # Gemini Enterprise Agent Platform / Agent Runtime
    "discoveryengine.googleapis.com",      # Agent Search / File Search (standalone house-view store)
    "bigquery.googleapis.com",             # Portfolio + client-profile store (internal data)
    "dlp.googleapis.com",                  # Sensitive Data Protection / DLP (PII redaction)
    "modelarmor.googleapis.com",           # Model Armor guardrail
    "logging.googleapis.com",              # Cloud Logging (WORM locked bucket + audit)
    "cloudtrace.googleapis.com",           # Cloud Trace (OpenTelemetry spans)
    "run.googleapis.com",                  # Cloud Run job / app host
    "secretmanager.googleapis.com",        # App secrets (no secrets in code, P-04)
    "cloudkms.googleapis.com",             # Regional CMEK key ring (P-09)
    "accesscontextmanager.googleapis.com", # VPC Service Controls perimeter (P-03)
    "assuredworkloads.googleapis.com",     # Assured Workloads (sovereignty controls, P-03)
    # Supporting services the above transitively require.
    "compute.googleapis.com",   # VPC
    "iam.googleapis.com",       # Service accounts / least-privilege IAM
    "orgpolicy.googleapis.com", # Org Policy residency constraints (P-03)
  ]
}

resource "google_project_service" "required" {
  for_each = toset(local.required_services)

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}
