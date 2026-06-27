resource "google_cloud_scheduler_job" "pipeline" {
  name        = "hermes-pipeline"
  description = "Triggers Hermes multi-agent pipeline run every 6 hours"
  schedule    = "0 */6 * * *"
  time_zone   = "America/Mexico_City"
  region      = var.region
  project     = var.project_id

  http_target {
    http_method = "POST"
    uri         = "${var.brain_url}/run"

    oidc_token {
      service_account_email = var.scheduler_sa_email
    }
  }

  retry_config {
    retry_count = 1
  }
}
