# cost:quote — Estima el costo de UNA operación sin ejecutar nada

Estima el costo de la operación descrita en `$ARGUMENTS`. No ejecuta nada, no llama a otros
skills, no modifica ningún archivo.

## Parámetros
`$ARGUMENTS` — descriptor de operación en formato libre. Ejemplos:
- `gcp: Cloud Run service hermes-brain, 1vCPU 512MB, ~100h/mes`
- `llm: 1 corrida completa, free analysts + GPT-5.4 Mini PM, ~100K tokens`
- `gcp: terraform apply módulo cloud-sql, db-f1-micro, us-central1`

## Pasos

1. Parsear `$ARGUMENTS` para determinar tipo (`gcp` o `llm`) y recurso.

2. Si tipo es `gcp`:
   - Consultar precios públicos de GCP para el recurso descrito.
   - Calcular costo mensual estimado y costo one-time si aplica.
   - Indicar si es $0.00 (dentro del free tier) o costo real.

3. Si tipo es `llm`:
   - Usar tabla de precios del PRD §11.2 y variables `LLM_COST_*` de `.envrc`.
   - Calcular costo por corrida y proyección mensual a 4 corridas/día.

4. Emitir el bloque de cotización:
   ```
   ── cost:quote ────────────────────────────────────────────
   Operación  : <descripción>
   Tipo       : <gcp | llm>
   Estimado   : $X.XX USD <por corrida | por mes | one-time>
   Supuestos  : <lista de supuestos usados>
   Free tier  : <sí/no — detalle>
   ──────────────────────────────────────────────────────────
   ```

5. Terminar. No llamar `cost:gate`, no modificar ledgers.
