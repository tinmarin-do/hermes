locals {
  # Ejecución = Bitso (2026-07-03; key SIN permiso de retiro — PRD §8.3).
  # Binance queda solo como fuente de DATA pública (sin key necesaria).
  secrets = [
    "bitso-api-key",
    "bitso-api-secret",
    "deepseek-api-key",
    "openai-api-key",
    "db-password",
  ]
}

resource "google_secret_manager_secret" "secrets" {
  for_each  = toset(local.secrets)
  secret_id = "hermes-${each.key}"
  project   = var.project_id

  replication {
    auto {}
  }
}
