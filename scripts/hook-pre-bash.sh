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

# ── gatekeeper de costo: SUSPENDIDO para el arco H11 (directiva Erika 2026-07-11) ──
# Autonomía total en la nube: sin cotización inline ni aprobación por operación.
# La protección de gasto es el google_billing_budget (alertas 50%/80%, cap duro
# 80% = $232 de $290 antes de la meta). Los bloqueos destructivos de arriba SIGUEN.
# Para reactivar el gatekeeper al cerrar el arco: restaurar este bloque desde git
# (commit previo a feature/h11-lab-bootstrap).

exit 0
