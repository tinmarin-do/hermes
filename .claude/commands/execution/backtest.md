# execution:backtest — Backtest sobre histórico para UNA estrategia

Corre el pipeline completo de decisión sobre datos históricos Silver/Gold y simula
ejecución con slippage realista. No consume LLM en cloud — usa respuestas mock o Ollama local.

## Parámetros
`$ARGUMENTS` — formato: `<símbolo> <timeframe> <desde> <hasta>`
Ejemplo: `BTC/USDT 1h 2025-01-01 2026-01-01`

## Pasos

1. Verificar que Bronze/Silver existen para el rango. Si no: sugerir `/data:backfill`.

2. Ejecutar backtest:
   ```bash
   uv run python -m src.execution.backtest \
     --symbol "$SYMBOL" --timeframe "$TF" \
     --since "$SINCE" --until "$UNTIL"
   ```

3. Calcular métricas ajustadas por riesgo:
   - Sharpe ratio + PSR (Probabilistic Sharpe Ratio).
   - Sortino ratio.
   - Max drawdown.
   - Win rate, profit factor.
   - Intervalo de credibilidad bayesiano del Sharpe.

4. Mostrar reporte:
   ```
   ── execution:backtest ── BTC/USDT 1h ─────────────────────
   Período    : 2025-01-01 → 2026-01-01 (365 días)
   Trades     : XXX (X/día promedio)
   P&L total  : +X.XX% ($X.XX)
   Sharpe     : X.XX [90% CI: X.XX, X.XX]  (PSR: X.XX)
   Sortino    : X.XX
   Max DD     : -X.XX%
   Win rate   : XX%
   ──────────────────────────────────────────────────────────
   ⚠️ Muestra chica — PSR e intervalo bayesiano son relevantes.
   ```

## Notas
- Reportar siempre con honestidad incluyendo pérdidas.
- No usar backtest como promesa de rendimiento futuro.
