resource "google_cloud_scheduler_job" "pipeline" {
  name        = "hermes-pipeline"
  description = "Corrida DIARIA del pipeline (PRD v0.3 §8.8 — consume la línea pre-autorizada)"
  schedule    = "10 8 * * *" # 08:10 México, misma cadencia que el cron local
  time_zone   = "America/Mexico_City"
  region      = var.region
  project     = var.project_id

  # ACTIVO (2026-07-03): el brain real está desplegado; el cron WSL queda apagado.
  paused = false

  attempt_deadline = "1800s" # la corrida completa tarda ~15 min

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

# ── Watchdog de drawdown intradía (2026-07-04, decisión Erika) ─────────────────
# Cada 30 min → dashboard /api/check-drawdown. El dashboard está tras IAP:
# el OIDC lleva audience = client_id del CUSTOM OAuth de IAP (el gestionado por
# Google NO permite acceso programático — doc authentication-howto) y la SA
# tiene httpsResourceAccessor (módulo cloud-run).
resource "google_cloud_scheduler_job" "drawdown_watchdog" {
  name        = "hermes-drawdown-watchdog"
  description = "Vigía intradía: equity vivo vs snapshot oficial; breach → email + re-run (máx 1/día)"
  schedule    = "*/30 * * * *"
  time_zone   = "Etc/UTC" # cooldown (marker por día UTC) y cron en el MISMO reloj
  region      = var.region
  project     = var.project_id
  paused      = false

  attempt_deadline = "120s"

  http_target {
    http_method = "POST"
    uri         = "${var.dashboard_url}/api/check-drawdown"

    oidc_token {
      service_account_email = var.scheduler_sa_email
      audience              = var.iap_oauth_client_id
    }
  }

  retry_config {
    retry_count = 0 # el siguiente tick llega en 30 min; reintentar no aporta
  }
}

# Job PAUSADO de emergencia: el watchdog lo dispara con la secuencia
# resume → run → pause (un job pausado devuelve 400 a jobs.run — cicatriz
# 2026-07-03 redescubierta en el drill; y el validador de cron rechaza fechas
# imposibles tipo 31-feb, así que "activo sin cron real" no existe).
# El tráfico de Scheduler cuenta como interno → alcanza al brain INTERNAL_ONLY
# con force=true. retry_count=0 = CERO corridas duplicadas (la trampa que
# descartó a Pub/Sub: ack 600s < corrida ~15 min → redelivery).
resource "google_cloud_scheduler_job" "emergency_run" {
  name        = "hermes-emergency-run"
  description = "Re-run del comité ante drawdown — disparo vía watchdog (resume→run→pause)"
  schedule    = "0 0 1 1 *" # requerido por el API; jamás corre (paused salvo ~1s del disparo)
  time_zone   = "Etc/UTC"
  region      = var.region
  project     = var.project_id
  paused      = true

  attempt_deadline = "1800s" # cubre la corrida completa (~15 min)

  http_target {
    http_method = "POST"
    uri         = "${var.brain_url}/run?force=true"

    oidc_token {
      service_account_email = var.scheduler_sa_email
    }
  }

  retry_config {
    retry_count = 0
  }
}
