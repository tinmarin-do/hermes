# data:validate-bronze — Valida integridad de la capa Bronze para UN símbolo

Verifica que los datos en Bronze son completos, consistentes y listos para transformación.

## Parámetros
`$ARGUMENTS` — formato: `<símbolo> <timeframe>`
Ejemplo: `BTC/USDT 1h`

## Pasos

1. Parsear símbolo y timeframe.

2. Ejecutar validaciones:
   ```bash
   uv run python -m src.data.bronze.validate --symbol "$SYMBOL" --timeframe "$TF"
   ```
   Checks:
   - Schema correcto (open, high, low, close, volume presentes y numéricos).
   - Sin timestamps duplicados.
   - Sin valores nulos o negativos en OHLCV.
   - Gaps temporales: ningún gap > 3× el timeframe esperado.
   - Monotonía: timestamps en orden ascendente.
   - OHLC consistency: high >= max(open,close), low <= min(open,close).

3. Mostrar reporte:
   ```
   ── data:validate-bronze — BTC/USDT 1h ───────────────────
   Registros  : X,XXX
   Rango      : 2026-01-01 → 2026-06-26
   Gaps       : ✅ ninguno  /  ⚠️ X gaps detectados
   Nulos      : ✅ 0
   OHLC check : ✅ ok
   Schema     : ✅ ok
   Resultado  : ✅ VÁLIDO  /  ❌ INVÁLIDO
   ──────────────────────────────────────────────────────────
   ```

4. Si inválido: mostrar detalle de cada falla. Recomendar re-ingesta con `/data:ingest-bronze`.
