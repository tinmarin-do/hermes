resource "google_cloud_scheduler_job" "pipeline" {
  name        = "hermes-pipeline"
  description = "Corrida DIARIA del pipeline (PRD v0.3 §8.8 — consume la línea pre-autorizada)"
  schedule    = "10 8 * * *" # 08:10 México, misma cadencia que el cron local
  time_zone   = "America/Mexico_City"
  region      = var.region
  project     = var.project_id

  # PAUSADO hasta que el brain tenga imagen real con endpoint /run: evita fallos
  # diarios contra el placeholder Y la doble corrida con el cron WSL (que sigue
  # siendo el motor). Al desplegar el brain real: quitar y apagar el cron WSL.
  paused = true

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
