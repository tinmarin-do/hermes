resource "google_sql_database_instance" "hermes" {
  name             = "hermes-db"
  database_version = "POSTGRES_16"
  region           = var.region
  project          = var.project_id

  settings {
    tier              = "db-f1-micro"
    edition           = "ENTERPRISE" # el default de PG16 (ENTERPRISE_PLUS) no soporta shared-core
    availability_type = "ZONAL"

    backup_configuration {
      enabled = false
    }

    ip_configuration {
      # IP pública SIN redes autorizadas: solo accesible vía Cloud SQL Auth Proxy
      # con IAM (estándar seguro para POC; private IP exigiría VPC connector $$).
      ipv4_enabled = true
    }
  }

  deletion_protection = false
}

resource "google_sql_database" "hermes" {
  name     = "hermes"
  instance = google_sql_database_instance.hermes.name
  project  = var.project_id
}

resource "google_sql_user" "hermes" {
  name     = "hermes"
  instance = google_sql_database_instance.hermes.name
  password = var.db_password
  project  = var.project_id
}

output "connection_name" {
  value = google_sql_database_instance.hermes.connection_name
}
