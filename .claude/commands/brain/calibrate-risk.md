# brain:calibrate-risk — Calibra guardrails con backtest cuant + validación LLM

Corre la calibración de riesgo en dos fases sobre el histórico:
- **Fase 1 (cuant, sin LLM, sin costo):** backtest purgado + embargo sobre puntos de muestreo
  para fijar Kelly fraction y daily loss limit óptimos (precision/recall/F1, approval rate).
- **Fase 2 (LLM, con costo):** valida el pipeline multiagente sobre las fechas más volátiles.

Genera un reporte markdown con los guardrails óptimos. **La Fase 2 gasta tokens DeepSeek** —
requiere `cost:gate` antes.

## Parámetros
`$ARGUMENTS` — flags opcionales que se pasan a `src.brain.calibrate`:
- `--symbols BTC/USDT,ETH/USDT` (default: `HERMES_ALLOWED_SYMBOLS`)
- `--timeframe 1h`
- `--skip-llm` → solo Fase 1 (cuant, costo $0)
- `--concurrency N` → pipelines LLM concurrentes (default 2)
- `--debate-rounds N` → rondas de debate (default 1)
- `--model <path>` → modelo LightGBM entrenado (reemplaza heurística)
- `--train-model` → entrena el QuantCore antes de calibrar

## Pasos

1. Validar Gold disponible: `/data:validate-gold`. Si inválido, abortar.

2. **Si NO `--skip-llm`:** obtener el estimado de costo de la Fase 2 (sin invocar modelos).
   La calibración lo imprime al arrancar la Fase 2:
   `[cost] estimado LLM de la calibracion: ~$X.XXXX USD (N fechas × ~$Y)`.
   Llamar `/cost:gate` con ese estimado. Si rechaza: correr con `--skip-llm` o abortar.

3. Ejecutar:
   ```bash
   uv run python -m src.brain.calibrate $ARGUMENTS
   ```
   El núcleo de costo (`src.brain.cost_meter`) mide los tokens reales de la Fase 2.

4. **Si corrió Fase 2:** registrar el costo REAL. La calibración imprime la línea exacta:
   `[cost] registrar en ledger:  /cost:log llm|<fecha>|calibracion <run_id>|<costo_real>|auto`.
   Copiar ese argumento a `/cost:log` (no estimar). Queda persistido en `llm_cost_runs`.

5. Mostrar el reporte generado (`REPORT_PATH`) con:
   - Guardrails óptimos: `HERMES_KELLY_FRACTION`, `HERMES_DAILY_LOSS_LIMIT_PCT`.
   - Métricas: precision, recall, F1, approval rate, avg return aprobados vs rechazados.

## Notas
- Fase 1 es determinista y gratis — corré `--skip-llm` libremente para iterar guardrails.
- La calibración NO se re-corre por cada operación (rompería comparabilidad). Solo on-demand
  o cuando una métrica de drift lo dispara.
- Ver muestreo: `QUANT_TRAIN_FREQ` (default `W-MON`) controla la densidad de puntos.
