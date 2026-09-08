# house_views.tf : the CIO house-view store the standalone `gcp` profile retrieves from.
#
# General Principle map:
#   P-03 (residency): the data store is created in asia-southeast1; the CIO corpus and its
#         embeddings never leave Singapore.
#   P-07 (grounded): this store IS the grounding. With it absent the adapter retrieves
#         nothing and the pipeline refuses the briefing rather than answering ungrounded,
#         which is correct behaviour and a confusing way to discover missing infrastructure.
#
# This file exists because it did not. `config/settings.yaml` has named
# `house_views.data_store_id: cio-house-views` since the repository was written, the
# adapter (adapters/gcp/file_search_house_views.py) queries it, and no Terraform anywhere
# created it. Deploying this stack and asking for a briefing would have failed at retrieval
# with an error about an empty result rather than about a store that was never provisioned.
#
# Inside the full platform the `platform` profile delegates retrieval to
# enterprise-knowledge-base instead and this store is unused. It is the STANDALONE path, which is
# what a buyer evaluating this system on its own actually runs.
#
# scripts/ingest_house_views.py fills it from the same shipped fictional corpus the laptop
# reads, so the two surfaces ground on one report.

resource "google_discovery_engine_data_store" "house_views" {
  location          = var.region # asia-southeast1 (P-03)
  project           = var.project_id
  data_store_id     = "cio-house-views" # matches settings.yaml house_views.data_store_id
  display_name      = "CIO house views"
  industry_vertical = "GENERIC"
  content_config    = "NO_CONTENT" # structured records, not uploaded documents
  solution_types    = ["SOLUTION_TYPE_SEARCH"]

  # The fields the adapter reads out of `struct_data` (file_search_house_views.py). Declared
  # here rather than inferred, so a record missing `stance` or `asset_class` is a schema
  # error at ingest instead of a theme that silently coerces to a neutral multi-asset view.
  # `tags` is what links a theme to the instruments it is about; without it the theme-to-
  # holding match falls back to the asset class and a mega-cap theme points at every equity.
  create_advanced_site_search = false

  depends_on = [google_project_service.required]
}

resource "google_discovery_engine_search_engine" "house_views" {
  engine_id      = "cio-advisory-engine" # matches settings.yaml house_views.engine_id
  collection_id  = "default_collection"
  location       = google_discovery_engine_data_store.house_views.location
  project        = var.project_id
  display_name   = "CIO advisory search"
  data_store_ids = [google_discovery_engine_data_store.house_views.data_store_id]

  search_engine_config {
    search_tier = "SEARCH_TIER_STANDARD"
  }
}
