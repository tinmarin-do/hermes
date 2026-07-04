resource "google_cloud_run_v2_service" "dashboard" {
  name     = "hermes-dashboard"
  location = var.region
  project  = var.project_id

  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false # POC — sin protección para permitir replace

  template {
    service_account = var.runtime_sa_email

    containers {
      image = var.dashboard_image != "" ? var.dashboard_image : "gcr.io/cloudrun/hello"

      resources {
        limits = {
          cpu    = "1"
          memory = "256Mi"
        }
        cpu_idle = true # CPU solo durante requests (<512Mi lo exige; y es más barato)
      }

      env {
        name  = "HERMES_MODE"
        value = "cloud"
      }

      env {
        name  = "HERMES_STATE_BUCKET"
        value = var.state_bucket # snapshot.json del bucket de estado (cache 60s)
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

  ingress             = "INGRESS_TRAFFIC_INTERNAL_ONLY"
  deletion_protection = false # POC

  template {
    service_account = var.runtime_sa_email
    timeout         = "3600s" # la corrida diaria completa tarda ~15 min

    containers {
      image = var.brain_image != "" ? var.brain_image : "gcr.io/cloudrun/hello"

      resources {
        limits = {
          cpu    = "2"
          memory = "4Gi" # OOM real medido a 2Gi (torch+DeBERTa+UMAP+DuckDB) — 2026-07-03
        }
        cpu_idle = true # solo paga CPU durante la corrida diaria
      }

      env {
        name  = "HERMES_MODE"
        value = "cloud"
      }

      dynamic "env" {
        for_each = var.brain_plain_env
        content {
          name  = env.key
          value = env.value
        }
      }

      # Secretos como REFERENCIA (secret_key_ref): el valor solo existe dentro
      # del contenedor en runtime — jamás en código, plan, ni contexto (§8.3).
      dynamic "env" {
        for_each = var.brain_secret_env
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = env.value
              version = "latest"
            }
          }
        }
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

# ── IAP en el dashboard (2026-07-04) ───────────────────────────────────────────
# IAP se habilitó con `gcloud run services update hermes-dashboard --iap`; el
# provider google 6.50 NO conoce el campo iap_enabled del servicio v2, así que
# Terraform es ciego a ese flag (un apply no puede revertirlo — verificado en el
# schema). El cliente OAuth CUSTOM es OBLIGATORIO en este proyecto (sin
# organización, el cliente gestionado de Google no deja entrar a NADIE) y se
# configuró en Console (consent External + IAP Settings → Custom OAuth → Auto
# Generate); su client secret vive solo en IAP settings — fuera de TF a propósito.
data "google_project" "this" {
  project_id = var.project_id
}

# El agente de servicio de IAP necesita invocar el dashboard (gcloud --iap lo
# otorga solo; declarado aquí para sobrevivir un recreate del servicio).
resource "google_cloud_run_v2_service_iam_member" "dashboard_iap_agent" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.dashboard.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:service-${data.google_project.this.number}@gcp-sa-iap.iam.gserviceaccount.com"
}

# Quién pasa el proxy IAP — nivel servicio (suficiente: la herencia se verificó
# con Policy Troubleshooter; los bindings región/proyecto del debug son redundantes).
resource "google_iap_web_cloud_run_service_iam_member" "dashboard_accessor" {
  for_each = toset(var.dashboard_iap_accessors)

  project                = var.project_id
  location               = var.region
  cloud_run_service_name = google_cloud_run_v2_service.dashboard.name
  role                   = "roles/iap.httpsResourceAccessor"
  member                 = each.value
}
