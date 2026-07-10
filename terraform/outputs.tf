output "dashboard_url" {
  description = "Public URL of the Hermes dashboard"
  value       = module.cloud_run.dashboard_url
}

output "brain_url" {
  description = "Internal URL of the brain service"
  value       = module.cloud_run.brain_url
  sensitive   = true
}
