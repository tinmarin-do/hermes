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
