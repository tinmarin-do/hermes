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

      # Credencial Bitso READ-ONLY para el tile /api/live (2026-07-04): solo
      # consulta de balances — sin trading/retiro. Referencia, jamás valor.
      dynamic "env" {
        for_each = var.dashboard_secret_env
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

      # Watchdog de drawdown (threshold + nombre del job de emergencia)
      dynamic "env" {
        for_each = var.dashboard_plain_env
        content {
          name  = env.key
          value = env.value
        }
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

# RETIRADO (revisión final 2026-07-06): el flip `dashboard_public=true` (binding
# allUsers para demos, 2026-07-03) quedó OBSOLETO Y PELIGROSO desde que el
# dashboard sirve /api/live con balances reales de Bitso — hacerlo público
# expondría la cartera a internet. La vía para demos es IAP: agregar al viewer
# en `dashboard_iap_accessors` (+apply) y quitarlo al terminar.

# ── IAP en el dashboard (2026-07-04) ───────────────────────────────────────────
# ⚠️ PELIGRO CONOCIDO: el provider google 6.50 NO conoce iap_enabled (vive en
# google-beta) → ser "ciego" NO protege: un apply que toque este servicio PUEDE
# APAGAR IAP (ocurrió 2026-07-04, drill del watchdog — dashboard quedó 403).
# PROTOCOLO POST-APPLY obligatorio hasta migrar el recurso a google-beta/provider
# con iap_enabled (backlog prioritario):
#   gcloud run services update hermes-dashboard --iap --region us-central1
#   curl -sI <dashboard_url> | head -1   # debe ser 302 (redirect a login)
# El cliente OAuth CUSTOM es OBLIGATORIO en este proyecto (sin organización, el
# cliente gestionado no deja entrar a NADIE); se configuró en Console (consent
# External + IAP Settings → Custom OAuth); su client secret vive solo en IAP
# settings — fuera de TF a propósito. El custom client SOBREVIVE al toggle.
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

# El watchdog (SA del scheduler) pasa IAP para llamar /api/check-drawdown.
resource "google_iap_web_cloud_run_service_iam_member" "dashboard_watchdog_accessor" {
  project                = var.project_id
  location               = var.region
  cloud_run_service_name = google_cloud_run_v2_service.dashboard.name
  role                   = "roles/iap.httpsResourceAccessor"
  member                 = "serviceAccount:${var.scheduler_sa_email}"
}
