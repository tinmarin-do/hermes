#!/usr/bin/env bash
# Pre-bash hook — GATEKEEPER DE COSTO (regla de Erika, 2026-07-03).
#
# Claude Code manda JSON por stdin (el hook viejo leía $1 y era un no-op).
# 1) Todo comando gcloud/gsutil/bq/terraform-apply|destroy que Claude ejecute
#    DEBE llevar la cotización inline (`# cost-est: $X.XX — <qué es>`): así el
#    prompt de permisos le muestra a Erika el costo estimado EN la pantalla
#    donde autoriza. Sin marcador → se bloquea ANTES de pedirle permiso.
#    Tras ejecutar, registrar en el ledger vía /cost:log (regla #5).
# 2) Patrones destructivos: bloqueo duro incondicional.

INPUT=$(cat)
CMD=$(printf '%s' "$INPUT" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("command",""))' 2>/dev/null)

deny() {
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"%s"}}\n' "$1"
  exit 0
}

[ -z "$CMD" ] && exit 0

# ── destructivos: bloqueo duro ──
if printf '%s' "$CMD" | grep -qiE 'gsutil rm -r|DROP TABLE|rm -rf /'; then
  deny "🚫 patrón destructivo bloqueado por hook"
fi

# ── gatekeeper de costo: GCP/terraform sin cotización inline no pasa ──
if printf '%s' "$CMD" | grep -qE '(^|[;&|[:space:]])(gcloud|gsutil|bq)[[:space:]]|terraform[[:space:]]+(apply|destroy)'; then
  if ! printf '%s' "$CMD" | grep -q 'cost-est:'; then
    deny "GATEKEEPER: comando GCP/terraform sin cotizacion inline. Protocolo: (1) /cost:quote en el chat, (2) autorizacion de Erika, (3) re-ejecutar con sufijo: # cost-est: \$X.XX — <descripcion>. (4) Tras ejecutar: /cost:log."
  fi
fi

exit 0
