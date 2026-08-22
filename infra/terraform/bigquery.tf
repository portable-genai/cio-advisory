# bigquery.tf : Portfolio + client-profile dataset (internal customer data, CMEK).
#
# General Principle map:
#   P-03 (residency): the dataset is created in asia-southeast1; portfolios and KYC profiles
#         never leave Singapore.
#   P-09 (CMEK explicit): the dataset uses the regional CMEK from kms.tf (the BigQuery
#         service-agent key binding is in kms.tf).
#   P-04 (data minimisation): the app reads only what a briefing needs; PII is redacted at
#         the boundary before any text reaches a model or the audit log.
#
# This dataset backs the PortfolioPort (cio_advisory.adapters.gcp.bigquery_portfolio).
# The schema mirrors the columns the adapter selects (holdings + client_profiles).

resource "google_bigquery_dataset" "wealth_portfolio" {
  dataset_id  = "wealth_portfolio" # matches settings.yaml bigquery.dataset
  project     = var.project_id
  location    = var.region # asia-southeast1 (P-03)
  description = "Private-bank client portfolios and KYC profiles for B3 (internal, CMEK)."

  default_encryption_configuration {
    kms_key_name = google_kms_crypto_key.cio.id # CMEK does not cascade (P-09)
  }

  # Internal data : never world-readable.
  delete_contents_on_destroy = false

  depends_on = [
    google_project_service.required,
    google_kms_crypto_key_iam_member.bigquery,
  ]
}

resource "google_bigquery_table" "holdings" {
  dataset_id          = google_bigquery_dataset.wealth_portfolio.dataset_id
  table_id            = "holdings" # matches settings.yaml bigquery.portfolio_table
  project             = var.project_id
  deletion_protection = true

  schema = jsonencode([
    { name = "client_id", type = "STRING", mode = "REQUIRED" },
    { name = "instrument", type = "STRING", mode = "REQUIRED" },
    { name = "asset_class", type = "STRING", mode = "REQUIRED" },
    { name = "value", type = "FLOAT", mode = "REQUIRED" },
    { name = "weight", type = "FLOAT", mode = "REQUIRED" },
    { name = "currency", type = "STRING", mode = "NULLABLE" },
  ])
}

resource "google_bigquery_table" "client_profiles" {
  dataset_id          = google_bigquery_dataset.wealth_portfolio.dataset_id
  table_id            = "client_profiles" # matches settings.yaml bigquery.profile_table
  project             = var.project_id
  deletion_protection = true

  schema = jsonencode([
    { name = "client_id", type = "STRING", mode = "REQUIRED" },
    { name = "risk_appetite", type = "STRING", mode = "REQUIRED" },
    { name = "objectives", type = "STRING", mode = "REPEATED" },
    { name = "knowledge_experience", type = "STRING", mode = "NULLABLE" },
    { name = "constraints", type = "STRING", mode = "REPEATED" },
    { name = "jurisdiction", type = "STRING", mode = "NULLABLE" },
  ])
}
