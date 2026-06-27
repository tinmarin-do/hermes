#!/usr/bin/env bash
# Post-terraform hook: recuerda loggear el costo después de un apply exitoso.
echo "✅ terraform apply completado."
echo "⚠️  Recuerda ejecutar /cost:log para registrar la operación en docs/cost_ledger_gcp.md"
