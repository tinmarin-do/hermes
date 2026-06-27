# agents:debug — Inspecciona la transcripción de UNA corrida por ID

Muestra el debate completo entre agentes para una corrida específica. Solo lectura.

## Parámetros
`$ARGUMENTS` — `run_id` de la corrida. Ejemplo: `3f7a2b1c-...`
Si vacío: usa la corrida más reciente.

## Pasos

1. Buscar corrida en BD por `run_id`:
   ```bash
   uv run python -m src.brain.debug --run-id "$RUN_ID"
   ```

2. Mostrar transcripción formateada:
   ```
   ══ agents:debug — run_id: <id> ════════════════════════════
   Timestamp : 2026-06-26T03:00:00Z
   Régimen   : BTC/USDT → trending (Hurst: 0.62, σ_GARCH: 0.021)

   [RegimeClassifier] → "Mercado en régimen trending con alta confianza..."

   [Analyst-Technical] → "RSI en 58, MACD cruzando alcista..."
   [Analyst-Sentiment] → "Sentimiento neutral, sin noticias relevantes..."
   [Analyst-OnChain]   → "Flujos de exchange negativos (bullish)..."

   [Debate-Bull] → "..."
   [Debate-Bear] → "..."

   [Trader] → "Posición larga justificada por..."
   [Risk]   → "VaR 2σ: $8.20. Límite: $10.00. ✅ Aprobado. Kelly: $12.50"
   [PM]     → "Ejecutar BUY $12.50 BTC/USDT. Confianza: 72%"

   Decisión final : BUY $12.50 BTC/USDT
   Risk check     : ✅ APROBADO
   ═══════════════════════════════════════════════════════════
   ```

3. Si `run_id` no existe: listar las últimas 5 corridas disponibles.
