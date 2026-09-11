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
    # `dlp.user` grants the CALL and not `dlp.inspectTemplates.get`, so without this the
    # identity can ask DLP to redact and cannot read the template that says how.
    "roles/dlp.reader",
    # Screening is a permission ON THE TEMPLATE (`modelarmor.templates.useToSanitize*`), so an
    # identity that reaches Vertex and DLP is still refused by the guardrail without it.
    "roles/modelarmor.user",
    "roles/logging.logWriter", # write redacted audit events to the WORM sink
    "roles/cloudtrace.agent",  # OpenTelemetry spans (content OFF)
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

# --------------------- Embedding host's runtime identity -------------------- #
# A portal that mounts this console same-origin runs the API under a service account of the
# PORTAL's making. That identity is the one the container authenticates as, so without these
# grants the deployed app starts, authenticates, and then fails on its first BigQuery read,
# Agent Search query or guardrail call, which reads as a broken application rather than as a
# missing binding. Empty by default: an app deployed on its own needs none of this.
#
# Narrower than the serving identity above, deliberately. The host already grants every
# embedded identity its runtime baseline (logs, traces, metrics), so none of that is repeated.
# The portfolio read is granted on THIS dataset rather than project-wide, because a shared
# project holds other applications' datasets. No CMEK key grant: BigQuery decrypts through its
# own service agent (kms.tf), never through the caller.
locals {
  additional_serving_project_roles = [
    "roles/aiplatform.user",
    "roles/discoveryengine.viewer",
    "roles/bigquery.jobUser",
    "roles/dlp.user",
    "roles/dlp.reader",
    "roles/modelarmor.user",
  ]
}

resource "google_project_iam_member" "additional_serving" {
  for_each = {
    for pair in setproduct(var.additional_serving_service_accounts, local.additional_serving_project_roles) :
    "${pair[0]}|${pair[1]}" => { email = pair[0], role = pair[1] }
  }
  project = var.project_id
  role    = each.value.role
  member  = "serviceAccount:${each.value.email}"
}

resource "google_bigquery_dataset_iam_member" "additional_serving" {
  for_each   = toset(var.additional_serving_service_accounts)
  project    = var.project_id
  dataset_id = google_bigquery_dataset.wealth_portfolio.dataset_id
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${each.value}"
}
