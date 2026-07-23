output "research_bucket" {
  value       = google_storage_bucket.research.name
  description = "Bucket de research del arco H11"
}

output "lab_job_name" {
  value       = google_cloud_run_v2_job.lab.name
  description = "Cloud Run Job de experimentos"
}

output "lab_sa_email" {
  value       = google_service_account.lab.email
  description = "Service account del laboratorio"
}
