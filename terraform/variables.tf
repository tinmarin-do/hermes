variable "project_id" {
  type        = string
  description = "GCP project ID"
}

variable "region" {
  type        = string
  default     = "us-central1"
  description = "GCP region for all resources"
}

variable "dashboard_image" {
  type        = string
  description = "Container image for dashboard service (gcr.io/...)"
  default     = ""
}

variable "brain_image" {
  type        = string
  description = "Container image for brain service (gcr.io/...)"
  default     = ""
}


variable "capital_usd" {
  type        = number
  description = "Trading capital in USD"
  default     = 500
}

variable "environment" {
  type        = string
  description = "Environment: staging or production"
  default     = "staging"
  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "environment must be staging or production"
  }
}

variable "dashboard_iap_accessors" {
  type        = list(string)
  description = "Miembros con acceso IAP al dashboard (2026-07-04: acceso desde cel/compu de la operadora)"
  default     = ["user:teamarin563@gmail.com"]
}

variable "iap_oauth_client_id" {
  type        = string
  default     = "1059097028157-jigr45cvrs10p0d2eupjdn6kakam5co2.apps.googleusercontent.com"
  description = "Client ID del CUSTOM OAuth de IAP (extraído del redirect de login; NO es secreto — el client secret vive solo en IAP Settings, fuera de TF). Audience del OIDC del watchdog para pasar IAP."
}

variable "alert_email" {
  type        = string
  default     = "teamarin563@gmail.com"
  description = "Destinatario de alertas operativas (drawdown watchdog)"
}

variable "drawdown_alert_pct" {
  type        = string
  default     = "0.03"
  description = "Umbral de caída intradía vs snapshot oficial que dispara email + re-run (decisión 2026-07-04: −3%)"
}

# ── Arco H11: laboratorio de research cloud ──────────────────────────────────

variable "lab_image" {
  type        = string
  default     = ""
  description = "Imagen del job hermes-lab (vacío → lab:latest del AR del proyecto)"
}

variable "billing_account_id" {
  type        = string
  description = "Billing account de los créditos H11 (pasar vía TF_VAR_billing_account_id; no es secreto pero no se commitea)"
}

variable "research_budget_units" {
  type        = number
  default     = 290
  description = "Budget del arco en la moneda de la billing account"
}

variable "lab_vm_enabled" {
  type        = bool
  default     = false
  description = "VM spot de iteración interactiva del lab (default apagada)"
}
