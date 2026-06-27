#!/usr/bin/env bash
# Pre-bash hook: bloquea comandos de alto riesgo que requieren gate explícito.
# Claude Code ejecuta este hook antes de cada comando Bash.

CMD="$1"

BLOCKED_PATTERNS=(
    "terraform apply"
    "terraform destroy"
    "gcloud.*delete"
    "gcloud.*--quiet"
    "gsutil rm -r"
    "DROP TABLE"
    "rm -rf /"
)

for pattern in "${BLOCKED_PATTERNS[@]}"; do
    if echo "$CMD" | grep -qiE "$pattern"; then
        echo "🚫 HOOK BLOCKED: '$CMD' matches blocked pattern '$pattern'"
        echo "Usa el skill correspondiente (/infra:apply, /infra:gcloud, /infra:teardown) que incluye cost:gate."
        exit 1
    fi
done

exit 0
