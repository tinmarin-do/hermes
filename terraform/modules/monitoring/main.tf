# Alertas de Hermes — canal email + policy log-match para DRAWDOWN_BREACH.
# Diseño $0: condition_matched_log SIN google_logging_metric (cero metric
# references — gratis incluso bajo el pricing de alerting anunciado sep-2026;
# revisar la factura de septiembre por si Google cobrara log-match policies).

resource "google_monitoring_notification_channel" "operator_email" {
  project      = var.project_id
  display_name = "Hermes — operadora (email)"
  type         = "email"
  labels = {
    email_address = var.alert_email
  }
}

resource "google_monitoring_alert_policy" "drawdown_breach" {
  project      = var.project_id
  display_name = "Hermes — drawdown intradía superó el umbral"
  combiner     = "OR"
  severity     = "CRITICAL"

  conditions {
    display_name = "DRAWDOWN_BREACH en logs del dashboard"

    condition_matched_log {
      filter = <<-EOT
        resource.type="cloud_run_revision"
        resource.labels.service_name="hermes-dashboard"
        severity=ERROR
        jsonPayload.event="DRAWDOWN_BREACH"
      EOT
    }
  }

  alert_strategy {
    notification_rate_limit {
      period = "1800s" # máx 1 email cada 30 min (mismo paso que el watchdog)
    }
    auto_close = "86400s"
  }

  notification_channels = [google_monitoring_notification_channel.operator_email.id]

  documentation {
    content = <<-EOT
      La caída intradía del portafolio vs el snapshot oficial superó el umbral
      (HERMES_DRAWDOWN_ALERT_PCT). El watchdog re-disparó el pipeline para que el
      comité re-evalúe (máx 1 re-run automático/día UTC; después solo este email).
      Runbook: dashboard /api/live · /agents:status · marker watchdog/rerun-*.marker
      en el bucket de estado (borrarlo devuelve el cupo del día).
    EOT
  }
}
