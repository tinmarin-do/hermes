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

module "cloud_run" {
  source                  = "./modules/cloud-run"
  project_id              = var.project_id
  region                  = var.region
  dashboard_image         = var.dashboard_image
  brain_image             = var.brain_image
  dashboard_iap_accessors = var.dashboard_iap_accessors
  # Secretos creados vía gcloud 2026-07-04 (fuera del módulo secret-manager a
  # propósito: aquí solo se REFERENCIAN; el valor lo cargó la operadora).
  dashboard_secret_env = {
    BITSO_RO_KEY    = "hermes-bitso-readonly-key"
    BITSO_RO_SECRET = "hermes-bitso-readonly-secret"
  }
  dashboard_plain_env = {
    HERMES_DRAWDOWN_ALERT_PCT = var.drawdown_alert_pct
    # Nombre construido como LITERAL — referenciar el output del módulo scheduler
    # crearía un ciclo (scheduler ya depende de cloud_run por brain/dashboard_url).
    HERMES_EMERGENCY_JOB = "projects/${var.project_id}/locations/${var.region}/jobs/hermes-emergency-run"
  }
  scheduler_sa_email = google_service_account.scheduler.email
  runtime_sa_email   = google_service_account.runtime.email
  state_bucket       = google_storage_bucket.state.name
  brain_secret_env = {
    BITSO_API_KEY    = module.secret_manager.secret_ids["bitso-api-key"]
    BITSO_API_SECRET = module.secret_manager.secret_ids["bitso-api-secret"]
    DEEPSEEK_API_KEY = module.secret_manager.secret_ids["deepseek-api-key"]
    DB_PASSWORD      = module.secret_manager.secret_ids["db-password"]
  }
  brain_plain_env = {
    HERMES_STATE_BUCKET         = google_storage_bucket.state.name
    HERMES_DUCKDB_PATH          = "/tmp/hermes.duckdb"
    HERMES_ALLOWED_SYMBOLS      = "BTC/USDT,ETH/USDT,SOL/USDT,LINK/USDT,AVAX/USDT,XRP/USDT"
    HERMES_CAPITAL_USD          = "400"    # fallback/paper; en live manda el wallet (abajo)
    HERMES_BUDGET_SOURCE        = "wallet" # live: budget = equity real de Bitso (decisión 2026-07-03)
    HERMES_KELLY_FRACTION       = "0.10"   # calibrado 2026-07-03 (era interim; el óptimo coincidió)
    HERMES_DAILY_LOSS_LIMIT_PCT = "0.04"   # calibrado 2026-07-03 (antes default 0.02)
    HERMES_MAX_POSITIONS        = "6"
    EXCHANGE_MODE               = "live" # flip 2026-07-03 (decisión Erika): daily opera REAL en Bitso
    EXCHANGE_ID                 = "bitso"
    TOKENIZERS_PARALLELISM      = "false"
    DATA_EXCHANGE_ID            = "bitso" # Binance geo-bloquea GCP (451)
    NEWS_LABEL_WITH_LLM         = "0"
    HERMES_DAILY_LINE_CAP_USD   = "0.50"
  }
}

# SA de RUNTIME para los servicios: los secretos llegan como secret_key_ref —
# el valor solo existe dentro del contenedor (jamás en código/plan/contexto).
resource "google_service_account" "runtime" {
  project      = var.project_id
  account_id   = "hermes-runtime"
  display_name = "Hermes Runtime — accessor de secretos (menor privilegio)"
}

resource "google_secret_manager_secret_iam_member" "runtime_accessor" {
  for_each  = module.secret_manager.secret_ids
  project   = var.project_id
  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

# Bucket de ESTADO operacional (política de datos PRD §6): DuckDB operacional +
# snapshot del dashboard. El brain lo baja al arrancar y lo sube al terminar
# (1 corrida/día = sin concurrencia). El histórico completo vive en LOCAL.
resource "google_storage_bucket" "state" {
  project                     = var.project_id
  name                        = "hermes-state-${var.project_id}"
  location                    = var.region
  uniform_bucket_level_access = true
  versioning {
    enabled = true # rollback barato del libro si una corrida corrompe el archivo
  }
}

resource "google_storage_bucket_iam_member" "runtime_state" {
  bucket = google_storage_bucket.state.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.runtime.email}"
}

# Repositorio de imágenes (dashboard + brain) — us-central1, formato Docker.
resource "google_artifact_registry_repository" "hermes" {
  project       = var.project_id
  location      = var.region
  repository_id = "hermes"
  format        = "DOCKER"
  description   = "Imágenes de Hermes (dashboard + brain)"
}

# SA de menor privilegio: Cloud Scheduler SOLO puede invocar el brain (OIDC).
resource "google_service_account" "scheduler" {
  project      = var.project_id
  account_id   = "hermes-scheduler"
  display_name = "Hermes Scheduler — invoca el brain (menor privilegio)"
}

module "cloud_scheduler" {
  source              = "./modules/cloud-scheduler"
  project_id          = var.project_id
  region              = var.region
  brain_url           = module.cloud_run.brain_url
  dashboard_url       = module.cloud_run.dashboard_url
  iap_oauth_client_id = var.iap_oauth_client_id
  scheduler_sa_email  = google_service_account.scheduler.email
}

module "monitoring" {
  source      = "./modules/monitoring"
  project_id  = var.project_id
  alert_email = var.alert_email
}

# El dashboard (SA runtime) dispara el job de emergencia con la secuencia
# resume → run → pause (jobs.run rechaza jobs pausados). Rol CUSTOM de mínimo
# privilegio: solo esas 3 operaciones + get — Scheduler no tiene IAM por-job.
resource "google_project_iam_custom_role" "emergency_trigger" {
  project     = var.project_id
  role_id     = "hermesEmergencyTrigger"
  title       = "Hermes — disparo del job de emergencia"
  description = "resume/run/pause de jobs de Scheduler (watchdog de drawdown)"
  permissions = [
    "cloudscheduler.jobs.run",
    "cloudscheduler.jobs.enable",
    "cloudscheduler.jobs.pause",
    "cloudscheduler.jobs.get",
  ]
}

resource "google_project_iam_member" "runtime_job_runner" {
  project = var.project_id
  role    = google_project_iam_custom_role.emergency_trigger.id
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

# Audit logs de DECISIÓN de IAP (encendidos 2026-07-04 durante el debug del
# custom OAuth): sin ellos, un deny de IAP no deja rastro en ningún log.
resource "google_project_iam_audit_config" "iap" {
  project = var.project_id
  service = "iap.googleapis.com"

  audit_log_config {
    log_type = "ADMIN_READ"
  }
  audit_log_config {
    log_type = "DATA_READ"
  }
  audit_log_config {
    log_type = "DATA_WRITE"
  }
}

# Accessors de los secretos READ-ONLY del tile en vivo (secretos no gestionados
# por TF — creados vía gcloud 2026-07-04; aquí solo el IAM).
resource "google_secret_manager_secret_iam_member" "runtime_readonly_accessor" {
  for_each  = toset(["hermes-bitso-readonly-key", "hermes-bitso-readonly-secret"])
  project   = var.project_id
  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}
