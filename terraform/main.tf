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
  source      = "./modules/cloud-sql"
  project_id  = var.project_id
  region      = var.region
  db_password = var.db_password
}

module "cloud_run" {
  source             = "./modules/cloud-run"
  project_id         = var.project_id
  region             = var.region
  dashboard_image    = var.dashboard_image
  brain_image        = var.brain_image
  db_connection      = module.cloud_sql.connection_name
  dashboard_public   = var.dashboard_public
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
    HERMES_STATE_BUCKET       = google_storage_bucket.state.name
    HERMES_DUCKDB_PATH        = "/tmp/hermes.duckdb"
    HERMES_ALLOWED_SYMBOLS    = "BTC/USDT,ETH/USDT,SOL/USDT,LINK/USDT,AVAX/USDT,XRP/USDT"
    HERMES_CAPITAL_USD        = "400" # era-$400 paper (decisión 2026-07-03; live tras F6+calibración)
    HERMES_KELLY_FRACTION     = "0.10" # calibrado 2026-07-03 (era interim; el óptimo coincidió)
    HERMES_DAILY_LOSS_LIMIT_PCT = "0.04" # calibrado 2026-07-03 (antes default 0.02)
    HERMES_MAX_POSITIONS      = "6"
    EXCHANGE_MODE             = "paper"
    EXCHANGE_ID               = "bitso"
    TOKENIZERS_PARALLELISM    = "false"
    DATA_EXCHANGE_ID          = "bitso" # Binance geo-bloquea GCP (451)
    NEWS_LABEL_WITH_LLM       = "0"
    HERMES_DAILY_LINE_CAP_USD = "0.50"
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
  source             = "./modules/cloud-scheduler"
  project_id         = var.project_id
  region             = var.region
  brain_url          = module.cloud_run.brain_url
  scheduler_sa_email = google_service_account.scheduler.email
}
