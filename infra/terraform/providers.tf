# providers.tf : Provider pinning for the B3 CIO Advisory Assistant sovereign deploy.
#
# General Principle map:
#   P-03 (data residency / in-country): every provider call is pinned to the Singapore
#         region (var.region, default asia-southeast1). There is no global/multi-region default.
#   P-02 (no lock-in): Terraform is the only place infra is described; the app itself talks
#         to ports, not these resources.
#
# google-beta is required because several sovereignty resources (Model Armor templates,
# some Access Context Manager fields) are only exposed on the beta surface.

terraform {
  required_version = ">= 1.9.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0" # 6.x line : current GA surface (mid-2026)
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 6.0"
    }
  }
}

# Primary (GA) provider : every resource defaults to Singapore.
provider "google" {
  project = var.project_id
  region  = var.region # allowlisted deploy-time region : regional, never global
}

# Beta provider : same project/region, used only where a resource needs it.
provider "google-beta" {
  project = var.project_id
  region  = var.region
}
