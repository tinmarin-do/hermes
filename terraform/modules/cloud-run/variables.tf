variable "project_id" { type = string }
variable "region" { type = string }
variable "dashboard_image" { type = string }
variable "brain_image" { type = string }
variable "db_connection" { type = string }

output "dashboard_url" {
  value = google_cloud_run_v2_service.dashboard.uri
}

output "brain_url" {
  value     = google_cloud_run_v2_service.brain.uri
  sensitive = true
}
