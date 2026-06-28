# cost:status — Dashboard de gasto actual vs presupuestos

Lee ambos ledgers y muestra un resumen del estado de gasto. Solo lectura.

## Parámetros
Ninguno. `$ARGUMENTS` ignorado.

## Pasos

1. Leer `docs/cost_ledger_gcp.md` → extraer acumulado GCP y presupuesto total.

2. Leer `docs/cost_ledger_llm.md` → extraer acumulado mensual LLM y cap $150.00.

2b. Leer corridas MEDIDAS pero aún NO registradas en el ledger (gap de auditoría):
   ```bash
   uv run python -c "from src.data.db import get_connection; c=get_connection(); \
   r=c.execute(\"SELECT COUNT(*), COALESCE(SUM(cost_usd),0) FROM llm_cost_runs WHERE NOT logged_to_ledger\").fetchone(); \
   print(f'unlogged={r[0]} usd={r[1]:.4f}'); c.close()"
   ```
   Estas corridas las midió `src.brain.cost_meter` pero todavía no pasaron por `/cost:log`.

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
     Sin registrar: N corridas (~$X.XX) medidas pero no en el ledger ⏳

   Última operación GCP : <fecha> — <descripción>
   Última corrida LLM   : <fecha> — run_id <id>
   ══════════════════════════════════════════════════════════
   ```

5. Si hay corridas sin registrar (paso 2b > 0): recordar correr `/cost:log` con el costo real
   que imprimió cada corrida (ver `agents:run` / `brain:calibrate-risk`).

6. Si algún presupuesto supera 80%: mostrar advertencia ⚠️.
   Si supera 100%: mostrar alerta ❌ y recordar que `/agents:run` está pausado.
