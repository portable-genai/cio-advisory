# vpc_sc.tf : VPC Service Controls perimeter around the AI/data plane.
#
# General Principle map:
#   P-03 (residency + exfiltration control): a service perimeter draws a logical boundary
#         around the sovereignty-critical APIs (Vertex/Agent Platform, Agent Search,
#         BigQuery, DLP, Logging, KMS, Secret Manager, Storage). Data cannot be read across
#         the boundary to a non-Singapore project, which stops client portfolios and the
#         audit log from leaving the country.
#   P-01 (least surface): only the services B3 uses are inside the perimeter.
#
# Guarded by var.enable_vpc_sc so non-prod/dev applies can skip it (count = 0).
#
# DEPLOY-ORDER CAVEAT:
#   The perimeter blocks API calls from outside it. If you enable this BEFORE the resources
#   in the other files are created (or before your Terraform runner / CI identity is added
#   to the perimeter's access levels), those API calls will be denied and the apply will
#   fail. Recommended order:
#     1. Apply everything with enable_vpc_sc = false.
#     2. Add your operator/CI identity to an access level.
#     3. Re-apply with enable_vpc_sc = true to enforce the boundary.

locals {
  perimeter_restricted_services = [
    "aiplatform.googleapis.com",
    "discoveryengine.googleapis.com",
    "bigquery.googleapis.com",
    "dlp.googleapis.com",
    "modelarmor.googleapis.com",
    "logging.googleapis.com",
    "cloudtrace.googleapis.com",
    "cloudkms.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
  ]
}

resource "google_access_context_manager_service_perimeter" "cio" {
  count = var.enable_vpc_sc ? 1 : 0

  parent = "accessPolicies/${var.access_policy_id}"
  name   = "accessPolicies/${var.access_policy_id}/servicePerimeters/cio_advisory_sg"
  title  = "cio_advisory_sg"

  perimeter_type = "PERIMETER_TYPE_REGULAR"

  status {
    resources = ["projects/${data.google_project.this.number}"]

    restricted_services = local.perimeter_restricted_services

    vpc_accessible_services {
      enable_restriction = true
      allowed_services   = local.perimeter_restricted_services
    }
  }

  depends_on = [google_project_service.required]
}
