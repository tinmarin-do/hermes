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

# Job de emergencia SIEMPRE ACTIVO — tres cicatrices lo esculpieron:
# (1) jobs.run devuelve 400 sobre un job pausado (2026-07-03);
# (2) el validador de cron rechaza fechas imposibles (31-feb no existe);
# (3) pausar un job MATA su intento en vuelo (drill 2026-07-04: el finally
#     re-pausaba 1s después del run → attempt cancelado, comité jamás corrió).
# Solución: activo permanente con cron que COINCIDE con la corrida diaria
# (1-ene 08:10 MX) — su único disparo anual es un no-op (lock + guard anti-dup
# lo absorben). jobs.run funciona siempre, sin coreografía de estados.
# El tráfico de Scheduler cuenta como interno → alcanza al brain INTERNAL_ONLY
# con force=true. retry_count=0 = CERO corridas duplicadas (la trampa que
# descartó a Pub/Sub: ack 600s < corrida ~15 min → redelivery).
resource "google_cloud_scheduler_job" "emergency_run" {
  name        = "hermes-emergency-run"
  description = "Re-run del comité ante drawdown — disparo vía watchdog (jobs.run); cron anual = no-op deliberado"
  schedule    = "10 8 1 1 *" # 1-ene 08:10 MX = misma hora que el daily → colisión inofensiva
  time_zone   = "America/Mexico_City"
  region      = var.region
  project     = var.project_id
  paused      = false

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

# Job de validación manual SIEMPRE ACTIVO — mismo patrón que emergency_run de
# arriba (mismas tres cicatrices: jobs.run rechaza pausados, cron inválido,
# pausar mata el intento en vuelo). Dedicado a probar deploys/debug: corre el
# comité completo (shadow/news-forward/logs se escriben igual) pero CON
# execute=false — nunca toca el exchange. Incidente 2026-07-08: una corrida
# forzada para validar PR #38 reusó emergency_run (execute=true implícito) y
# el comité, no-determinista, dio un veredicto distinto al del daily 08:10 MX
# → ejecutó un rebalanceo real no buscado. Este job separa "¿el deploy
# funciona?" de "¿se le permite mover dinero?" — trigger manual con
# `gcloud scheduler jobs run hermes-manual-verify`; el watchdog de drawdown
# sigue disparando exclusivamente `hermes-emergency-run` (execute=true, única
# fuente legítima de reacción real a un breach).
resource "google_cloud_scheduler_job" "manual_verify" {
  name        = "hermes-manual-verify"
  description = "Validación manual del comité SIN ejecución real (dry-run) — deploys/debug; jobs.run manual; cron anual = no-op deliberado"
  schedule    = "10 8 1 1 *" # 1-ene 08:10 MX = misma hora que el daily → colisión inofensiva
  time_zone   = "America/Mexico_City"
  region      = var.region
  project     = var.project_id
  paused      = false

  attempt_deadline = "1800s" # cubre la corrida completa (~15 min)

  http_target {
    http_method = "POST"
    uri         = "${var.brain_url}/run?force=true&execute=false"

    oidc_token {
      service_account_email = var.scheduler_sa_email
    }
  }

  retry_config {
    retry_count = 0
  }
}
