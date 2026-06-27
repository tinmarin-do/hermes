locals {
  secrets = [
    "binance-api-key",
    "binance-api-secret",
    "binance-testnet-api-key",
    "binance-testnet-api-secret",
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
