# house_views.tf : the CIO house-view store the standalone `gcp` profile retrieves from.
#
# General Principle map:
#   P-03 (residency): Agent Search has no Cloud-region location at all, only `global`, `us` and
#         `eu`, so this store CANNOT sit in var.region. It sits at var.house_views_location
#         (default `us`, one named jurisdiction). For a deployment whose other resources are
#         regional that is a stated residency deviation: the fictional CIO corpus and its index
#         live there, while client data stays in the BigQuery dataset in var.region. Where this
#         stack writes the project's Org Policies, gcp.resourceLocations admits exactly the two
#         location groups (org_policy.tf), so the posture the policy enforces is the posture the
#         stack actually has, never a policy that refuses the stack's own store.
#   P-07 (grounded): this store IS the grounding. With it absent or empty the adapter retrieves
#         nothing and the pipeline refuses the briefing rather than answering ungrounded.
#   P-09 (CMEK): the store carries no customer-managed key, and not by omission. Agent Search
#         accepts only a `us` or `eu` key, registered to the project's location BEFORE the store
#         is created, and documents CMEK for Enterprise edition only. The regional key in kms.tf
#         can never be one, and the engine below is Standard tier, so the store uses
#         Google-managed encryption, and org_policy.tf leaves discoveryengine.googleapis.com out
#         of the services restrictNonCmekServices denies.
#
# Where the store lives is ONE setting shared by both halves. This file creates it at
# var.house_views_location; the API reads CIO_HOUSE_VIEWS_LOCATION (config/settings.yaml), whose
# default is the same `us`; the loader writes through the API's own adapter.
# tests/contract/test_house_view_store_location.py fails when the defaults, the allowed values or
# the ids below disagree, which is the defect that otherwise surfaces only at the first briefing:
# a store at one location and a query at another.
#
# Inside the full platform the `platform` profile delegates retrieval to
# enterprise-knowledge-base instead and this store is unused.
#
# scripts/ingest_house_views.py fills it from the same shipped fictional corpus the laptop reads,
# stamped with the tenant the deployment's identity adapter resolves.

locals {
  # The gcp.resourceLocations value that admits the store: a location group for the two
  # jurisdictional locations, the literal for `global`, which is no group's member.
  house_views_location_policy_value = var.house_views_location == "global" ? "global" : "in:${var.house_views_location}-locations"
}

resource "google_discovery_engine_data_store" "house_views" {
  location          = var.house_views_location # NOT var.region: Agent Search serves no region (P-03)
  project           = var.project_id
  data_store_id     = "cio-house-views" # settings.yaml house_views.data_store_id
  display_name      = "CIO house views"
  industry_vertical = "GENERIC"
  content_config    = "NO_CONTENT" # structured records, not uploaded documents
  solution_types    = ["SOLUTION_TYPE_SEARCH"]

  create_advanced_site_search = false

  depends_on = [google_project_service.required]
}

resource "google_discovery_engine_search_engine" "house_views" {
  engine_id      = "cio-advisory-engine" # settings.yaml house_views.engine_id; retrieval searches this engine
  collection_id  = "default_collection"
  location       = google_discovery_engine_data_store.house_views.location
  project        = var.project_id
  display_name   = "CIO advisory search"
  data_store_ids = [google_discovery_engine_data_store.house_views.data_store_id]

  search_engine_config {
    search_tier = "SEARCH_TIER_STANDARD"
  }
}
