# shared_project_declines.tftest.hcl : what a shared-project deployment declines, as plans.
#
# Every run uses mock providers and is plan-only, so the file runs with NO credentials, NO
# project and NO state beyond the provider download:
#
#   terraform init -backend=false && terraform test
#
# which is what `make tf-check` runs. Nothing here is applied anywhere and every value is
# fictional. A decline that lives only in a variable description is a claim nobody checks; each
# run below is the check.

mock_provider "google" {}
mock_provider "google-beta" {}

variables {
  project_id = "fictional-wealth-project"
  org_id     = "123456789012"
}

run "a_sibling_stack_in_a_shared_project_declines_what_it_does_not_own" {
  command = plan

  variables {
    worm_locked                         = false
    retention_days                      = 30
    manage_org_policies                 = false
    manage_audit_config                 = false
    enable_vpc_sc                       = false
    model_armor_full_capabilities       = false
    additional_serving_service_accounts = ["journey-a-fictional@fictional-wealth-project.iam.gserviceaccount.com"]
  }

  assert {
    condition = (
      length(google_org_policy_policy.resource_locations) +
      length(google_org_policy_policy.no_external_ip) +
      length(google_org_policy_policy.uniform_bucket_access) +
      length(google_org_policy_policy.restrict_cmek_projects)
    ) == 0
    error_message = "A stack that does not own the project's Org Policies must write none of them."
  }

  assert {
    condition     = length(google_project_iam_audit_config.data_access) == 0
    error_message = "The authoritative project audit config must be declinable: applying it replaces a sibling's."
  }

  assert {
    condition     = length(google_access_context_manager_service_perimeter.cio) == 0
    error_message = "A second regular perimeter must not arrive in a project whose perimeter another stack owns."
  }

  assert {
    condition     = google_logging_project_bucket_config.worm_audit.locked == false
    error_message = "worm_locked = false must leave the audit bucket unlocked and destroyable."
  }

  assert {
    condition     = length(google_model_armor_template.cio_guardrail.filter_config[0].malicious_uri_filter_settings) == 0
    error_message = "A region that does not serve the malicious-URI filter must be able to decline it, or the template is refused."
  }

  assert {
    condition     = google_bigquery_dataset.wealth_portfolio.location == var.region
    error_message = "The client book must stay in the deployment region."
  }

  assert {
    condition     = google_bigquery_dataset_iam_member.additional_serving["journey-a-fictional@fictional-wealth-project.iam.gserviceaccount.com"].role == "roles/bigquery.dataViewer"
    error_message = "The embedding host's identity must be able to read THIS dataset."
  }

  assert {
    condition     = !contains([for member in values(google_project_iam_member.additional_serving) : member.role], "roles/bigquery.dataViewer")
    error_message = "The embedding host's identity must read this dataset, not every dataset in a shared project."
  }

  assert {
    condition = alltrue([
      for role in ["roles/aiplatform.user", "roles/discoveryengine.viewer", "roles/bigquery.jobUser", "roles/dlp.user", "roles/dlp.reader", "roles/modelarmor.user"] :
      contains([for member in values(google_project_iam_member.additional_serving) : member.role], role)
    ])
    error_message = "The embedding host's identity must hold every role a briefing reaches: models, house views, queries, DLP templates and the guardrail."
  }
}

run "a_fork_on_its_own_project_keeps_every_control" {
  command = plan

  variables {
    worm_locked      = true
    access_policy_id = "987654321098"
  }

  assert {
    condition = (
      length(google_org_policy_policy.resource_locations) +
      length(google_org_policy_policy.no_external_ip) +
      length(google_org_policy_policy.uniform_bucket_access) +
      length(google_org_policy_policy.restrict_cmek_projects)
    ) == 4
    error_message = "With no override, the stack must write all four residency and hardening policies."
  }

  assert {
    condition     = length(google_project_iam_audit_config.data_access) == 1 && length(google_access_context_manager_service_perimeter.cio) == 1
    error_message = "With no override, the audit config and the perimeter must both be created."
  }

  assert {
    condition     = google_logging_project_bucket_config.worm_audit.locked && google_logging_project_bucket_config.worm_audit.retention_days == 2557
    error_message = "A deployment that names worm_locked = true must get the locked seven-year bucket."
  }

  assert {
    condition     = length(google_model_armor_template.cio_guardrail.filter_config[0].malicious_uri_filter_settings) == 1
    error_message = "With no override, the guardrail must ask for the malicious-URI filter."
  }

  assert {
    condition     = length(google_project_iam_member.additional_serving) == 0 && length(google_bigquery_dataset_iam_member.additional_serving) == 0
    error_message = "An app deployed on its own must grant nothing to identities it did not create."
  }
}

run "a_locked_bucket_refuses_a_short_window" {
  command = plan

  variables {
    worm_locked    = true
    retention_days = 30
    enable_vpc_sc  = false
  }

  expect_failures = [var.retention_days]
}

run "an_embedding_identity_must_be_a_service_account" {
  command = plan

  variables {
    worm_locked                         = false
    enable_vpc_sc                       = false
    additional_serving_service_accounts = ["someone@example.test"]
  }

  expect_failures = [var.additional_serving_service_accounts]
}
