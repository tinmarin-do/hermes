variable "project_id" { type = string }
variable "region" { type = string }
variable "dashboard_image" { type = string }
variable "brain_image" { type = string }
variable "db_connection" { type = string }

variable "dashboard_public" {
  type        = bool
  default     = false
  description = "true = dashboard accesible por allUsers (demo); false = solo IAM (privado)"
}

variable "scheduler_sa_email" {
  type        = string
  description = "SA del Cloud Scheduler — recibe run.invoker SOLO sobre el brain"
}

output "dashboard_url" {
  value = google_cloud_run_v2_service.dashboard.uri
}

output "brain_url" {
  value     = google_cloud_run_v2_service.brain.uri
  sensitive = true
}
