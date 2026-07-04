variable "project_id" { type = string }
variable "region" { type = string }
variable "brain_url" { type = string }
variable "scheduler_sa_email" { type = string }
variable "dashboard_url" { type = string }
variable "iap_oauth_client_id" {
  type        = string
  description = "Client ID del custom OAuth de IAP (NO es secreto) — audience del OIDC para pasar IAP"
}
