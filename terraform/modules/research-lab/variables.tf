variable "project_id" {
  type        = string
  description = "GCP project ID"
}

variable "region" {
  type        = string
  description = "Región de bucket/job (us-central1)"
}

variable "lab_image" {
  type        = string
  default     = ""
  description = "Imagen del job hermes-lab; vacío → <region>-docker.pkg.dev/<project>/hermes/lab:latest"
}

variable "billing_account_id" {
  type        = string
  description = "Billing account (formato XXXXXX-XXXXXX-XXXXXX) donde viven los créditos del arco H11"
}

variable "budget_units" {
  type        = number
  default     = 290
  description = "Monto del budget en la MONEDA de la billing account (290 si factura USD; ajustar si MXN)"
}

variable "alert_email" {
  type        = string
  description = "Destinatario de las alertas de presupuesto (50%/80%)"
}

variable "vm_enabled" {
  type        = bool
  default     = false
  description = "Enciende la VM spot c2d-highcpu-32 de iteración interactiva (default: apagada)"
}

variable "scheduler_sa_email" {
  type        = string
  description = "SA de Cloud Scheduler que dispara la emisión diaria del shadow H12"
}
