# cost:gate — Autorización explícita de una operación con costo

Muestra cotización + acumulado + restante del presupuesto y solicita confirmación explícita
del usuario antes de proceder. Si el presupuesto está agotado, bloquea sin opción.

## Parámetros
`$ARGUMENTS` — descriptor de operación (mismo formato que `cost:quote`).

## Pasos

1. Llamar internamente a `cost:quote` con `$ARGUMENTS` para obtener el estimado.

2. Leer el ledger correspondiente:
   - Si tipo `gcp`: leer `docs/cost_ledger_gcp.md`, obtener acumulado y restante.
   - Si tipo `llm`: leer `docs/cost_ledger_llm.md`, obtener acumulado mensual y restante.

3. Mostrar el bloque de gate:
   ```
   ══ cost:gate ═══════════════════════════════════════════════
   Operación    : <descripción>
   Costo est.   : $X.XX USD
   Acumulado    : $X.XX USD
   Restante     : $X.XX USD  ← cap: $XXX.XX
   Estado       : ✅ DENTRO DEL PRESUPUESTO  /  ❌ CAP EXCEDIDO
   ═══════════════════════════════════════════════════════════
   ¿Autorizar esta operación? (sí / no)
   ```

4. Si el restante < costo estimado: mostrar `❌ CAP EXCEDIDO`, NO proceder, terminar.

5. Esperar confirmación explícita del usuario:
   - `sí` / `yes` / `s` / `y` → continuar con la operación que disparó este gate.
   - Cualquier otra respuesta → abortar, NO ejecutar nada.

6. Si autorizado: llamar `cost:log` con los datos de la operación autorizada.

## Notas
- Este skill nunca ejecuta la operación en sí — solo autoriza. El skill llamante ejecuta.
- `status: blocked` en el contrato de agentes corresponde a paso 4 (cap excedido).
