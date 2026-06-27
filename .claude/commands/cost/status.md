# cost:status — Dashboard de gasto actual vs presupuestos

Lee ambos ledgers y muestra un resumen del estado de gasto. Solo lectura.

## Parámetros
Ninguno. `$ARGUMENTS` ignorado.

## Pasos

1. Leer `docs/cost_ledger_gcp.md` → extraer acumulado GCP y presupuesto total.

2. Leer `docs/cost_ledger_llm.md` → extraer acumulado mensual LLM y cap $150.00.

3. Calcular porcentajes de uso.

4. Mostrar dashboard:
   ```
   ══ cost:status ═══════════════════════════════════════════
   GCP Infra
     Acumulado : $X.XX / $XXX.XX  (XX%)  ██████░░░░
     Restante  : $X.XX

   LLM Tokens (mes en curso)
     Acumulado : $X.XX / $150.00  (XX%)  ████░░░░░░
     Restante  : $X.XX
     Proyección: $X.XX/mes a 4 corridas/día

   Última operación GCP : <fecha> — <descripción>
   Última corrida LLM   : <fecha> — run_id <id>
   ══════════════════════════════════════════════════════════
   ```

5. Si algún presupuesto supera 80%: mostrar advertencia ⚠️.
   Si supera 100%: mostrar alerta ❌ y recordar que `/agents:run` está pausado.
