#!/usr/bin/env bash
# Stop hook: garantiza que el heartbeat de continuidad quede al día antes de que
# la sesión pase a idle (incluye el cierre). Claude Code ejecuta este hook cuando
# el agente principal termina de responder, pasando el JSON del evento por stdin.
#
# Persiste entre sesiones (vive en disco, no en memoria como un cron de sesión) y
# no expira. Reemplaza al cron de 3 min que era session-only.
#
# Lógica: si el heartbeat lleva >STALE_MINUTES sin tocarse, pide a Claude que lo
# refresque (decision: block) antes de terminar. Gateado por mtime para no molestar
# en cada turno, y por stop_hook_active para no entrar en bucle.

set -euo pipefail

HEARTBEAT="/home/tea/.claude/projects/-home-tea-hermes/memory/session-heartbeat.md"
STALE_MINUTES="${HERMES_HEARTBEAT_STALE_MIN:-10}"

input="$(cat)"

# Guard anti-bucle: si este stop ya fue provocado por el propio stop hook, dejar pasar.
if echo "$input" | grep -qE '"stop_hook_active"[[:space:]]*:[[:space:]]*true'; then
    exit 0
fi

# Si el heartbeat aún no existe (otro contribuidor / otra máquina), no bloquear.
[[ -f "$HEARTBEAT" ]] || exit 0

# Si se actualizó dentro de la ventana, está fresco → permitir el stop.
if [[ -n "$(find "$HEARTBEAT" -mmin "-${STALE_MINUTES}" 2>/dev/null)" ]]; then
    exit 0
fi

# Stale → pedir a Claude que lo refresque antes de pasar a idle.
cat <<'JSON'
{"decision":"block","reason":"Protocolo de continuidad: antes de terminar, actualiza memory/session-heartbeat.md (Última actualización, Estado actual, Próximo paso) reflejando el progreso real de esta sesión. Mantenlo compacto. Si NO hubo progreso significativo desde la última escritura, no reescribas el contenido — solo ejecuta `touch` sobre el archivo para refrescar su timestamp y termina."}
JSON
