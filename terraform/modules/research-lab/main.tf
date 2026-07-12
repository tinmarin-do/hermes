# Hermes Research Lab — arco H11 (2026-07-11).
# Laboratorio de experimentos 100% cloud: bucket de research, Cloud Run Job
# parametrizable, billing budget REAL (reemplaza a los ledgers markdown en el
# arco) y VM spot opcional (toggle apagado por default).

data "google_project" "this" {
  project_id = var.project_id
}

locals {
  lab_image = var.lab_image != "" ? var.lab_image : "${var.region}-docker.pkg.dev/${var.project_id}/hermes/lab:latest"
}

# ── Bucket de research: datasets, modelos, experimentos, reportes ──────────────
resource "google_storage_bucket" "research" {
  project                     = var.project_id
  name                        = "hermes-research-${var.project_id}"
  location                    = var.region
  uniform_bucket_level_access = true

  lifecycle_rule {
    condition {
      age            = 30
      matches_prefix = ["tmp/"]
    }
    action {
      type = "Delete"
    }
  }
}

# ── SA del laboratorio: menor privilegio (solo SU bucket + leer imágenes) ──────
resource "google_service_account" "lab" {
  project      = var.project_id
  account_id   = "hermes-lab"
  display_name = "Hermes Lab — jobs de research H11 (menor privilegio)"
}

resource "google_storage_bucket_iam_member" "lab_research" {
  bucket = google_storage_bucket.research.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.lab.email}"
}

resource "google_project_iam_member" "lab_ar_reader" {
  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.lab.email}"
}

# ── Cloud Run Job: experimentos + ingesta Bitso ────────────────────────────────
# El corpus Binance NO se refresca desde aquí (geo-block 451): llega por el
# cable local (delta + gcloud storage cp). Args sobreescribibles por ejecución:
#   gcloud run jobs execute hermes-lab --args="src.lab.experiment,--spec,gs://…"
resource "google_cloud_run_v2_job" "lab" {
  project             = var.project_id
  name                = "hermes-lab"
  location            = var.region
  deletion_protection = false

  template {
    task_count  = 1
    parallelism = 1

    template {
      service_account = google_service_account.lab.email
      timeout         = "3600s"
      max_retries     = 0

      containers {
        image = local.lab_image
        # Default seguro: selftest (escribe experiments/selftest.json y sale).
        args = ["src.lab.experiment", "--selftest"]

        env {
          name  = "HERMES_RESEARCH_BUCKET"
          value = google_storage_bucket.research.name
        }

        resources {
          limits = {
            cpu    = "8"
            memory = "16Gi"
          }
        }
      }
    }
  }
}

# ── Shadow pre-firewall H12 (DESIGN_H12 §12): emisión diaria del campeón ──────
# Job DEDICADO con args fijos (papel, cero riesgo, no toca el stack live): un
# :run con overrides exigiría run.jobs.runWithOverrides (no está en run.invoker,
# verificado 2026-07-12 con 403) — el job propio mantiene el mínimo privilegio.
# Cadencia de REBALANCEO = 28d la decide el producer (grilla anclada); la
# emisión diaria solo acumula evidencia AUC.
# 00:20 UTC: la barra diaria D cierra a las 00:00 — se decide con el día completo.
resource "google_cloud_run_v2_job" "shadow" {
  project             = var.project_id
  name                = "hermes-shadow-h12"
  location            = var.region
  deletion_protection = false

  template {
    task_count  = 1
    parallelism = 1

    template {
      service_account = google_service_account.lab.email
      timeout         = "1200s"
      max_retries     = 0

      containers {
        image = local.lab_image
        args  = ["src.lab.shadow_producer", "--emit"]

        env {
          name  = "HERMES_RESEARCH_BUCKET"
          value = google_storage_bucket.research.name
        }

        resources {
          limits = {
            cpu    = "2"
            memory = "4Gi"
          }
        }
      }
    }
  }
}

resource "google_cloud_run_v2_job_iam_member" "shadow_scheduler_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.shadow.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${var.scheduler_sa_email}"
}

resource "google_cloud_scheduler_job" "shadow_emit" {
  project          = var.project_id
  region           = var.region
  name             = "hermes-shadow-h12-emit"
  description      = "Shadow pre-firewall ext5-h28: delta Bitso + señal diaria + eval (§12)"
  schedule         = "20 0 * * *"
  time_zone        = "Etc/UTC"
  attempt_deadline = "180s"

  retry_config {
    retry_count = 1
  }

  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/jobs/${google_cloud_run_v2_job.shadow.name}:run"
    oauth_token {
      service_account_email = var.scheduler_sa_email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }
}

# ── Billing budget REAL — la protección de gasto del arco ─────────────────────
# EXCLUDE_ALL_CREDITS es CRÍTICO: con créditos incluidos el costo neto es $0 y
# las alertas del 50/80% jamás dispararían. Regla dura del arco: no pasar del
# 80% de los créditos sin haber alcanzado la meta (F1≥0.60 OOS + ~1%/día MXN).
resource "google_project_service" "billingbudgets" {
  project            = var.project_id
  service            = "billingbudgets.googleapis.com"
  disable_on_destroy = false
}

resource "google_monitoring_notification_channel" "lab_email" {
  project      = var.project_id
  display_name = "Hermes Lab — alertas de presupuesto H11 (email)"
  type         = "email"
  labels = {
    email_address = var.alert_email
  }
}

resource "google_billing_budget" "research" {
  billing_account = var.billing_account_id
  display_name    = "Hermes H11 — créditos research"

  budget_filter {
    projects               = ["projects/${data.google_project.this.number}"]
    credit_types_treatment = "EXCLUDE_ALL_CREDITS"
  }

  amount {
    specified_amount {
      # Sin currency_code: usa la moneda de la billing account (verificar unidades
      # al apply — si la cuenta factura en MXN, ajustar var.budget_units).
      units = tostring(var.budget_units)
    }
  }

  threshold_rules {
    threshold_percent = 0.5
  }
  threshold_rules {
    threshold_percent = 0.8
  }

  all_updates_rule {
    monitoring_notification_channels = [google_monitoring_notification_channel.lab_email.id]
    disable_default_iam_recipients   = false
  }

  depends_on = [google_project_service.billingbudgets]
}

# ── VM spot OPCIONAL (toggle apagado): iteración interactiva si los jobs quedan
# cortos. Encenderla = -var lab_vm_enabled=true + apply (requiere compute API).
resource "google_compute_instance" "lab_vm" {
  count        = var.vm_enabled ? 1 : 0
  project      = var.project_id
  name         = "hermes-lab-vm"
  machine_type = "c2d-highcpu-32"
  zone         = "${var.region}-a"

  scheduling {
    provisioning_model          = "SPOT"
    preemptible                 = true
    automatic_restart           = false
    instance_termination_action = "STOP"
  }

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-12"
      size  = 50
    }
  }

  network_interface {
    network = "default"
    access_config {}
  }

  service_account {
    email  = google_service_account.lab.email
    scopes = ["cloud-platform"]
  }
}
