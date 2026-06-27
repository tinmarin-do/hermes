resource "google_sql_database_instance" "hermes" {
  name             = "hermes-db"
  database_version = "POSTGRES_16"
  region           = var.region
  project          = var.project_id

  settings {
    tier              = "db-f1-micro"
    availability_type = "ZONAL"

    backup_configuration {
      enabled = false
    }

    ip_configuration {
      ipv4_enabled = false
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
