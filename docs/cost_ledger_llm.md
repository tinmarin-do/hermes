# Cost Ledger — Hermes LLM (mensual)

Presupuesto LLM (POC sprint): **$40.00 USD** | Mensual post-POC: **$150.00 USD**.
Tope POC total (GCP $10 + LLM $40): **$50.00 USD**.
Cada fila representa una corrida de agentes autorizada. Se reinicia el día 1 de cada mes vía `/cost:reset-llm`.
**No editar manualmente** — solo vía `/cost:log`.

Referencia de precios (DeepSeek V4 Flash unificado — todos los roles, junio 2026):
- Precio `.envrc`: input **$0.14** / output **$0.28** por 1M tokens.
- Todos los agentes (Regime, Analysts, Bull/Bear/Debate, Trader, Risk ×3, PM) usan DeepSeek V4 Flash.
- **Costo real medido por corrida: ~$0.007** (≈37K tokens, ej. run `99a9066d`).
- **4 corridas/día → ~$0.83/mes** (vía medición real de `src.brain.cost_meter`).
- Calibración LLM: ~N_fechas × ~$0.007 por fecha validada.
- Costo capturado automáticamente por token (no estimado a mano) — ver `src/brain/cost_meter.py`.

| fecha | corrida_id | modelo_pm | roles_pagados | tokens_totales | costo_usd | acumulado_mes (USD) | restante_mes (USD) |
|-------|------------|-----------|---------------|----------------|-----------|---------------------|--------------------|
| — | — | — | — | — | — | 0.00 | 150.00 |
| 2026-06-28 | 99a9066d | DeepSeek V4 Flash | all (18 llamadas) | 36927 | 0.0069 | 0.0069 | 149.9931 |
| 2026-06-28 | f4ff8143 | DeepSeek V4 Flash | all (18 llamadas) | 37225 | 0.0070 | 0.0139 | 149.9861 |
| 2026-06-28 | 86bd66ac | DeepSeek V4 Flash | all (e2e test) | 33320 | 0.0062 | 0.0201 | 149.9799 |
| 2026-06-28 | 19469923 | DeepSeek V4 Flash | all (e2e via pytest tests/ — NO gateada) | 54053 | 0.0101 | 0.0302 | 149.9698 |
| CIERRE-MES | 2026-06 | — | — | — | 0.0302 | 0.00 | REINICIO → 150.00 |
| 2026-07-02 | APERTURA-MES | — | — | — | 0.00 | 0.00 | 150.00 |
| 2026-07-02 | 672f54f0 | DeepSeek V4 Flash | all (e2e suite Fase 1 — gateada) | 55364 | 0.0104 | 0.0104 | 149.9896 |
| 2026-07-02 | 40b2cb70 | DeepSeek V4 Flash | all (run 6 símbolos Fase 1 — gateada) | 55656 | 0.0103 | 0.0207 | 149.9793 |
| 2026-07-02 | PRE-AUTORIZACIÓN | DeepSeek V4 Flash | línea corridas diarias julio (cap $0.50; ~$0.0105/día × ~29d; el cron se frena al superarla — §8.8) | — | ≤0.50 | 0.0207 | 149.9793 |
