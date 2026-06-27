# agents:status — Estado de la corrida activa o última

Muestra el estado del pipeline: si hay una corrida activa, su progreso; si no, el resumen
de la última corrida completada.

## Parámetros
Ninguno.

## Pasos

1. Consultar BD para corrida activa (`status = 'running'`).

2. Si hay corrida activa:
   ```
   ── agents:status ── CORRIDA ACTIVA ───────────────────────
   run_id   : <uuid>
   Inicio   : hace X minutos
   Etapa    : [RegimeClassifier ✅] [Analysts ✅] [Debate 🔄] [Trader ⏳] [Risk ⏳] [PM ⏳]
   ──────────────────────────────────────────────────────────
   ```

3. Si no hay corrida activa, mostrar resumen de la última:
   ```
   ── agents:status ── ÚLTIMA CORRIDA ───────────────────────
   run_id   : <uuid>
   Timestamp: 2026-06-26T03:00:00Z (hace X horas)
   Decisión : BUY BTC/USDT $12.50 | Risk: ✅
   Duración : X.X segundos
   Costo LLM: $0.13
   ──────────────────────────────────────────────────────────
   ```

4. Mostrar próxima corrida programada (si Cloud Scheduler está activo).
