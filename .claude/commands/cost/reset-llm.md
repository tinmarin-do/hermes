# cost:reset-llm — Reinicia el contador mensual de LLM

Archiva el mes anterior y reinicia el acumulado mensual en el ledger LLM.
Ejecutar el día 1 de cada mes (o manualmente tras confirmar cambio de mes).

## Parámetros
`$ARGUMENTS` — mes a cerrar en formato `YYYY-MM`. Ejemplo: `2026-06`

## Pasos

1. Verificar que `$ARGUMENTS` sea un mes válido en formato `YYYY-MM`.

2. Leer `docs/cost_ledger_llm.md` y extraer:
   - Todas las filas del mes `$ARGUMENTS`.
   - Total gastado en ese mes.

3. Agregar una fila de cierre al ledger:
   ```
   | CIERRE-MES | $ARGUMENTS | — | — | — | <total_mes> | 0.00 | REINICIO → 150.00 |
   ```

4. Agregar una fila de apertura del nuevo mes:
   ```
   | <fecha_hoy> | APERTURA-MES | — | — | — | 0.00 | 0.00 | 150.00 |
   ```

5. Confirmar: `✅ cost:reset-llm — mes $ARGUMENTS cerrado. Total: $X.XX. Nuevo ciclo iniciado.`

## Notas
- No borra filas del mes anterior — las deja en el ledger como historial.
- Si el mes ya fue cerrado (existe fila CIERRE-MES), reportar error y no duplicar.
