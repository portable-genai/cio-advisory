# posture_defaults.tftest.hcl: the reversible posture controls are OFF unless stated.
#
# Slice 7 of the 2026-09-23 posture rule (2026-10-01): a compliance control that is not
# irreversible defaults off in code, and terraform.tfvars.example carries the production
# form. This file pins that default with mock providers only, like the rest of the suite.

mock_provider "google" {}
mock_provider "google-beta" {}

# Required variables with no default, stated only so the plan runs.
variables {
  project_id = "fictional-wealth-project"
  org_id     = "123456789012"
}

run "reversible_posture_controls_default_off" {
  command = plan

  variables {
    cmek_enabled                        = true
    worm_locked                         = false
    retention_days                      = 30
    manage_org_policies                 = false
    manage_audit_config                 = false
    model_armor_full_capabilities       = false
    additional_serving_service_accounts = ["journey-a-fictional@fictional-wealth-project.iam.gserviceaccount.com"]
  }

  assert {
    condition     = length(google_access_context_manager_service_perimeter.cio) == 0
    error_message = "enable_vpc_sc defaults to false: no perimeter unless the deployment states it."
  }
}
