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

variable "runtime_sa_email" {
  type        = string
  description = "SA de runtime de los servicios (accessor de secretos, menor privilegio)"
}

variable "brain_secret_env" {
  type        = map(string)
  default     = {}
  description = "ENV_VAR → secret_id de Secret Manager (se inyectan como secret_key_ref)"
}

variable "brain_plain_env" {
  type        = map(string)
  default     = {}
  description = "Env vars NO sensibles del brain (config operacional)"
}

variable "state_bucket" {
  type        = string
  default     = ""
  description = "Bucket de estado operacional (DuckDB + snapshot del dashboard)"
}

output "dashboard_url" {
  value = google_cloud_run_v2_service.dashboard.uri
}

output "brain_url" {
  value     = google_cloud_run_v2_service.brain.uri
  sensitive = true
}

variable "dashboard_iap_accessors" {
  type        = list(string)
  description = "Miembros IAM con acceso al dashboard vía IAP (formato user:email)"
  default     = []
}

variable "dashboard_secret_env" {
  type        = map(string)
  description = "Env del dashboard como secret_key_ref (nombre de secreto SM). Solo credenciales READ-ONLY — la key operativa jamás toca el servicio expuesto."
  default     = {}
}
