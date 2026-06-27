terraform {
  required_version = ">= 1.9"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
  backend "gcs" {
    # bucket y prefix definidos en backend.tf (no commitear con valores reales)
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

module "secret_manager" {
  source     = "./modules/secret-manager"
  project_id = var.project_id
}

module "cloud_sql" {
  source     = "./modules/cloud-sql"
  project_id = var.project_id
  region     = var.region
}

module "cloud_run" {
  source            = "./modules/cloud-run"
  project_id        = var.project_id
  region            = var.region
  dashboard_image   = var.dashboard_image
  brain_image       = var.brain_image
  db_connection     = module.cloud_sql.connection_name
}

module "cloud_scheduler" {
  source     = "./modules/cloud-scheduler"
  project_id = var.project_id
  region     = var.region
  brain_url  = module.cloud_run.brain_url
}
