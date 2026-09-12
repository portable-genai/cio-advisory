# org_policy.tf : Org Policy constraints enforcing Singapore residency.
#
# General Principle map:
#   P-03 (data residency, defence in depth): even if someone hand-edits a resource, these
#         org policies REJECT the creation of resources outside Singapore.
#         gcp.resourceLocations is the master residency control; the rest harden the project
#         (no public IPs on VMs, uniform bucket access) so data and compute stay in-country
#         and private (P-05).
#
# Scoped to the project via google_project. To enforce org-wide, move these to an org-level
# google_org_policy_policy with parent = "organizations/${var.org_id}".
#
# Every policy here is gated on var.manage_org_policies. A project holds ONE value per
# constraint, so in a project another stack already governs these are declined rather than
# fought over: see that variable for what applying them into a shared project would break.

# Master residency policy: the selected var.region's location group, plus the ONE location the
# house-view store needs. Agent Search serves no Cloud region (house_views.tf), so a policy that
# admitted the region alone would refuse this stack's own store at apply; the stack states the
# two-location posture it actually has instead, and the tftest holds the list to exactly these.
# Narrowing it back to one jurisdiction means not holding the store: retrieve through the
# platform profile's governed knowledge base instead.
resource "google_org_policy_policy" "resource_locations" {
  count  = var.manage_org_policies ? 1 : 0
  name   = "projects/${var.project_id}/policies/gcp.resourceLocations"
  parent = "projects/${var.project_id}"

  spec {
    rules {
      values {
        allowed_values = distinct(["in:${var.region}-locations", local.house_views_location_policy_value])
      }
    }
  }

  depends_on = [google_project_service.required]
}

# Disable VM external IPs : keep the data plane private (P-05).
resource "google_org_policy_policy" "no_external_ip" {
  count  = var.manage_org_policies ? 1 : 0
  name   = "projects/${var.project_id}/policies/compute.vmExternalIpAccess"
  parent = "projects/${var.project_id}"

  spec {
    rules {
      deny_all = "TRUE"
    }
  }

  depends_on = [google_project_service.required]
}

# Require uniform bucket-level access (no per-object ACL exfiltration paths).
resource "google_org_policy_policy" "uniform_bucket_access" {
  count  = var.manage_org_policies ? 1 : 0
  name   = "projects/${var.project_id}/policies/storage.uniformBucketLevelAccess"
  parent = "projects/${var.project_id}"

  spec {
    rules {
      enforce = "TRUE"
    }
  }

  depends_on = [google_project_service.required]
}

# Restrict which services may skip CMEK : keep crypto in this project/region.
#
# discoveryengine.googleapis.com is deliberately NOT denied. Agent Search takes only a `us` or `eu`
# key registered ahead of the store, on Enterprise edition, so the house-view store carries no
# key (house_views.tf, P-09) and a policy denying the service would refuse the stack's own store.
resource "google_org_policy_policy" "restrict_cmek_projects" {
  count  = var.manage_org_policies ? 1 : 0
  name   = "projects/${var.project_id}/policies/gcp.restrictNonCmekServices"
  parent = "projects/${var.project_id}"

  spec {
    rules {
      values {
        denied_values = [
          "bigquery.googleapis.com",
          "logging.googleapis.com",
        ]
      }
    }
  }

  depends_on = [google_project_service.required]
}
