# cost:log — Registra UNA operación autorizada en el ledger

Appends una fila al ledger de costos correspondiente. Solo llamar después de que `cost:gate`
haya recibido autorización explícita del usuario. NUNCA llamar directamente.

## Parámetros
`$ARGUMENTS` — debe contener todos estos campos separados por `|`:
`<tipo>|<fecha>|<descripción>|<costo_usd>|<autorizado_por>`

Ejemplo:
`gcp|2026-06-26|terraform apply: Cloud Run hermes-brain (1vCPU 512MB)|0.00|usuario`

## Pasos

1. Parsear `$ARGUMENTS` para extraer: tipo, fecha, descripción, costo_usd, autorizado_por.

2. Determinar el ledger destino:
   - `gcp` → `docs/cost_ledger_gcp.md`
   - `llm` → `docs/cost_ledger_llm.md`

3. Leer el ledger para obtener el acumulado actual y calcular el nuevo acumulado.

4. Para GCP: calcular nuevo restante = presupuesto_total - nuevo_acumulado.
   Para LLM: calcular nuevo restante_mes = $150.00 - nuevo_acumulado_mes.

5. Append la nueva fila a la tabla del ledger con todos los campos correctos.

6. Confirmar: `✅ cost:log — entrada registrada en <ledger>`.

## Notas
- No preguntar confirmación — ya fue dada en `cost:gate`.
- Si el ledger no existe, reportar error y NO crear — indica problema de configuración.
