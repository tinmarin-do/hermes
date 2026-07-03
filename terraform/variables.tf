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

variable "dashboard_public" {
  type        = bool
  default     = false
  description = "Dashboard PRIVADO por default (decisión 2026-07-03). Flip a true solo para demos: terraform apply -var dashboard_public=true"
}

variable "db_password" {
  type        = string
  sensitive   = true
  default     = ""
  description = "Password del usuario SQL — pasar desde Secret Manager: TF_VAR_db_password=$(gcloud secrets versions access latest --secret=hermes-db-password). JAMÁS plaintext."
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
