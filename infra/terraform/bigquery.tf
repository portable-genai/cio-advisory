# bigquery.tf : the client book (internal customer data, CMEK).
#
# General Principle map:
#   P-03 (residency): the dataset is created in asia-southeast1; portfolios and KYC profiles
#         never leave Singapore.
#   P-09 (CMEK explicit): the dataset uses the regional CMEK from kms.tf (the BigQuery
#         service-agent key binding is in kms.tf).
#   P-04 (data minimisation): the app reads only what a briefing needs; PII is redacted at
#         the boundary before any text reaches a model or the audit log.
#
# This dataset backs the PortfolioPort (cio_advisory.adapters.gcp.bigquery_portfolio) and it
# holds the SAME five tables, in the same column order, as the DuckDB book the local and live
# profiles read (adapters/local/portfolio.py). One book, two stores, so the laptop and the
# deployment can be compared rather than merely both work.
#
# The schema and the adapter are held together by execution, not by care:
# tests/contract/test_demo_book.py parses this file and fails when the adapter selects a
# column declared here. It was written against the `tenant` column below, which the adapter
# had selected since it was written and this file had never declared. The managed profile
# would have failed on its first profile read, in front of whoever deployed it.
#
# scripts/load_demo_book.py fills these tables from the shipped fictional book. It refuses a
# dataset holding rows whose book_manifest does not say `fictional`, so it can never be the
# thing that truncates a real client book.

resource "google_bigquery_dataset" "wealth_portfolio" {
  dataset_id  = "wealth_portfolio" # matches settings.yaml bigquery.dataset
  project     = var.project_id
  location    = var.region # asia-southeast1 (P-03)
  description = "Private-bank client book: profiles, holdings, instruments and model portfolios (internal, CMEK)."

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

# One position per client and instrument. `instrument_id` references instruments.instrument_id
# rather than repeating an instrument's display name per client: BigQuery enforces no foreign
# key, so the book's own validator does (cio_advisory.demo_book.validate).
resource "google_bigquery_table" "holdings" {
  dataset_id          = google_bigquery_dataset.wealth_portfolio.dataset_id
  table_id            = "holdings" # matches settings.yaml bigquery.portfolio_table
  project             = var.project_id
  deletion_protection = true

  # The dataset's default_encryption_configuration stamps this key onto every table BigQuery
  # creates in it, so the live table carries an encryption_configuration whether or not this
  # resource declares one. Leaving it undeclared makes a later plan read the server-set block as
  # a REMOVAL, and removing it FORCES REPLACEMENT of the table, which destroys every row it
  # holds. Observed 2026-09-12 against this dataset's five loaded tables. CMEK does not cascade
  # in Terraform's model even though it does in BigQuery's, which is why the key is named twice.
  encryption_configuration {
    kms_key_name = google_kms_crypto_key.cio.id
  }

  schema = jsonencode([
    { name = "client_id", type = "STRING", mode = "REQUIRED" },
    { name = "instrument_id", type = "STRING", mode = "REQUIRED" },
    { name = "line_no", type = "INTEGER", mode = "REQUIRED" },
    { name = "value", type = "FLOAT", mode = "REQUIRED" },
    { name = "weight", type = "FLOAT", mode = "REQUIRED" },
    { name = "currency", type = "STRING", mode = "NULLABLE" },
    { name = "as_of_date", type = "DATE", mode = "REQUIRED" },
  ])
}

# The suitability profile a briefing is assessed against. `tenant` is the server-side
# object-authorization owner the entitlement gate reads (domain/entitlements.py): a row
# without one is owner-less and fails closed, and it is never client-asserted. On a
# deployment the tenant is whatever the identity adapter resolves from the IAP assertion, so
# the loader takes it as an argument rather than baking the demo value in.
resource "google_bigquery_table" "client_profiles" {
  dataset_id          = google_bigquery_dataset.wealth_portfolio.dataset_id
  table_id            = "client_profiles" # matches settings.yaml bigquery.profile_table
  project             = var.project_id
  deletion_protection = true

  # The dataset's default_encryption_configuration stamps this key onto every table BigQuery
  # creates in it, so the live table carries an encryption_configuration whether or not this
  # resource declares one. Leaving it undeclared makes a later plan read the server-set block as
  # a REMOVAL, and removing it FORCES REPLACEMENT of the table, which destroys every row it
  # holds. Observed 2026-09-12 against this dataset's five loaded tables. CMEK does not cascade
  # in Terraform's model even though it does in BigQuery's, which is why the key is named twice.
  encryption_configuration {
    kms_key_name = google_kms_crypto_key.cio.id
  }

  schema = jsonencode([
    { name = "client_id", type = "STRING", mode = "REQUIRED" },
    { name = "tenant", type = "STRING", mode = "REQUIRED" },
    { name = "risk_appetite", type = "STRING", mode = "REQUIRED" },
    { name = "objectives", type = "STRING", mode = "REPEATED" },
    { name = "knowledge_experience", type = "STRING", mode = "NULLABLE" },
    { name = "constraints", type = "STRING", mode = "REPEATED" },
    { name = "jurisdiction", type = "STRING", mode = "NULLABLE" },
    { name = "currency", type = "STRING", mode = "NULLABLE" },
    { name = "segment", type = "STRING", mode = "NULLABLE" },
    { name = "time_horizon_years", type = "INTEGER", mode = "NULLABLE" },
    { name = "last_review_date", type = "DATE", mode = "NULLABLE" },
    { name = "as_of_date", type = "DATE", mode = "REQUIRED" },
  ])
}

# Instrument reference data. `theme_tags` is what links a holding to a CIO house-view theme
# deterministically, instead of asking a model which of a client's positions a theme is about.
resource "google_bigquery_table" "instruments" {
  dataset_id          = google_bigquery_dataset.wealth_portfolio.dataset_id
  table_id            = "instruments" # matches settings.yaml bigquery.instruments_table
  project             = var.project_id
  deletion_protection = true

  # The dataset's default_encryption_configuration stamps this key onto every table BigQuery
  # creates in it, so the live table carries an encryption_configuration whether or not this
  # resource declares one. Leaving it undeclared makes a later plan read the server-set block as
  # a REMOVAL, and removing it FORCES REPLACEMENT of the table, which destroys every row it
  # holds. Observed 2026-09-12 against this dataset's five loaded tables. CMEK does not cascade
  # in Terraform's model even though it does in BigQuery's, which is why the key is named twice.
  encryption_configuration {
    kms_key_name = google_kms_crypto_key.cio.id
  }

  schema = jsonencode([
    { name = "instrument_id", type = "STRING", mode = "REQUIRED" },
    { name = "name", type = "STRING", mode = "REQUIRED" },
    { name = "asset_class", type = "STRING", mode = "REQUIRED" },
    { name = "sub_class", type = "STRING", mode = "NULLABLE" },
    { name = "region", type = "STRING", mode = "NULLABLE" },
    { name = "theme_tags", type = "STRING", mode = "REPEATED" },
    { name = "esg", type = "BOOLEAN", mode = "NULLABLE" },
    { name = "liquidity", type = "STRING", mode = "NULLABLE" },
  ])
}

# The ideal allocation per risk profile: what a portfolio is measured AGAINST, so a gap is a
# number of points and an amount rather than the absence of an asset class. It is data with an
# effective date rather than configuration because a bank revises it per quarter and per
# booking centre. The concentration limit stays in config/settings.yaml: that is a policy
# number, not a market view.
resource "google_bigquery_table" "model_portfolios" {
  dataset_id          = google_bigquery_dataset.wealth_portfolio.dataset_id
  table_id            = "model_portfolios" # matches settings.yaml bigquery.model_portfolio_table
  project             = var.project_id
  deletion_protection = true

  # The dataset's default_encryption_configuration stamps this key onto every table BigQuery
  # creates in it, so the live table carries an encryption_configuration whether or not this
  # resource declares one. Leaving it undeclared makes a later plan read the server-set block as
  # a REMOVAL, and removing it FORCES REPLACEMENT of the table, which destroys every row it
  # holds. Observed 2026-09-12 against this dataset's five loaded tables. CMEK does not cascade
  # in Terraform's model even though it does in BigQuery's, which is why the key is named twice.
  encryption_configuration {
    kms_key_name = google_kms_crypto_key.cio.id
  }

  schema = jsonencode([
    { name = "model_id", type = "STRING", mode = "REQUIRED" },
    { name = "risk_appetite", type = "STRING", mode = "REQUIRED" },
    { name = "jurisdiction", type = "STRING", mode = "NULLABLE" },
    { name = "asset_class", type = "STRING", mode = "REQUIRED" },
    { name = "target_weight", type = "FLOAT", mode = "REQUIRED" },
    { name = "min_weight", type = "FLOAT", mode = "REQUIRED" },
    { name = "max_weight", type = "FLOAT", mode = "REQUIRED" },
    { name = "effective_from", type = "DATE", mode = "REQUIRED" },
    { name = "source", type = "STRING", mode = "NULLABLE" },
  ])
}

# What this dataset holds and whether it may be replaced. `fictional` is the loader's
# overwrite guard: a populated dataset without a fictional manifest is somebody's real book
# and the loader refuses it. Deliberately not deletion-protected, because the loader rewrites
# this row on every load and the guard is the control, not the protection flag.
resource "google_bigquery_table" "book_manifest" {
  dataset_id          = google_bigquery_dataset.wealth_portfolio.dataset_id
  table_id            = "book_manifest" # matches settings.yaml bigquery.manifest_table
  project             = var.project_id
  deletion_protection = false

  # Declared for the same reason as its siblings above: the dataset stamps its key onto every
  # table, and an undeclared block reads as a removal, which replaces the table. This one is the
  # only table of the five a replacement may destroy cheaply, and it was destroyed exactly that
  # way on 2026-09-12, which is how the guard that reads it learned the dataset held no book.
  encryption_configuration {
    kms_key_name = google_kms_crypto_key.cio.id
  }

  schema = jsonencode([
    { name = "book_version", type = "STRING", mode = "REQUIRED" },
    { name = "as_of_date", type = "DATE", mode = "REQUIRED" },
    { name = "fictional", type = "BOOLEAN", mode = "REQUIRED" },
    { name = "loaded_at", type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "source_commit", type = "STRING", mode = "NULLABLE" },
    { name = "tenant", type = "STRING", mode = "REQUIRED" },
  ])
}
