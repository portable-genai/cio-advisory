# iam.tf : Least-privilege service accounts for the B3 workloads.
#
# General Principle map:
#   P-06 (least privilege / separation of duties): two distinct identities : the app
#         (serving) and the agent runtime (in agent_runtime.tf). Each gets only the roles it
#         needs; no shared "kitchen-sink" SA. This supports maker-checker separation.
#   P-03 (residency): identities are project-scoped; data access is to in-region services.
#   P-09 (CMEK explicit): each SA that touches CMEK-encrypted data gets its own cryptoKey
#         use binding.

# ------------------------------- App (serving) ------------------------------ #
resource "google_service_account" "app" {
  account_id   = "cio-advisory-app"
  display_name = "B3 CIO Advisory Assistant app (serving / API)"
  project      = var.project_id

  depends_on = [google_project_service.required]
}

locals {
  # Serving path: query house views, read portfolios (BigQuery), call models + guardrail +
  # DLP, write audit + traces, read secrets. No write to the portfolio store from serving.
  app_roles = [
    "roles/aiplatform.user",
    "roles/discoveryengine.viewer", # query the house-view store (read)
    "roles/bigquery.dataViewer",    # read portfolios + client profiles (read)
    "roles/bigquery.jobUser",       # run the read queries
    "roles/dlp.user",               # deidentifyContent (P-04)
    "roles/logging.logWriter",      # write redacted audit events to the WORM sink
    "roles/cloudtrace.agent",       # OpenTelemetry spans (content OFF)
    "roles/secretmanager.secretAccessor",
    "roles/run.invoker",
  ]
}

resource "google_project_iam_member" "app" {
  for_each = toset(local.app_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.app.email}"
}

# App uses the CMEK for envelope ops it performs directly.
resource "google_kms_crypto_key_iam_member" "app" {
  crypto_key_id = google_kms_crypto_key.cio.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:${google_service_account.app.email}"
}
