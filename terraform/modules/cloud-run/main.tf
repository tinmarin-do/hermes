resource "google_cloud_run_v2_service" "dashboard" {
  name     = "hermes-dashboard"
  location = var.region
  project  = var.project_id

  ingress = "INGRESS_TRAFFIC_ALL"

  template {
    containers {
      image = var.dashboard_image != "" ? var.dashboard_image : "gcr.io/cloudrun/hello"

      resources {
        limits = {
          cpu    = "1"
          memory = "256Mi"
        }
      }

      env {
        name  = "HERMES_MODE"
        value = "cloud"
      }
    }

    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }
  }

  lifecycle {
    ignore_changes = [template[0].containers[0].image]
  }
}

resource "google_cloud_run_v2_service" "brain" {
  name     = "hermes-brain"
  location = var.region
  project  = var.project_id

  ingress = "INGRESS_TRAFFIC_INTERNAL_ONLY"

  template {
    containers {
      image = var.brain_image != "" ? var.brain_image : "gcr.io/cloudrun/hello"

      resources {
        limits = {
          cpu    = "2"
          memory = "1Gi"
        }
      }

      env {
        name  = "HERMES_MODE"
        value = "cloud"
      }
    }

    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }
  }

  lifecycle {
    ignore_changes = [template[0].containers[0].image]
  }
}

# Menor privilegio: la SA del scheduler SOLO invoca el brain (nada más).
resource "google_cloud_run_v2_service_iam_member" "brain_scheduler_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.brain.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${var.scheduler_sa_email}"
}

# Privacidad del dashboard (decisión 2026-07-03): PRIVADO por default — el binding
# allUsers solo existe si dashboard_public=true. Flip a público para demos =
# cambiar la variable + apply (segundos, reversible). Acceso privado del owner:
#   gcloud run services proxy hermes-dashboard --region <region>
resource "google_cloud_run_v2_service_iam_member" "dashboard_public" {
  count = var.dashboard_public ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.dashboard.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
