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
| 2026-07-03 | 7bb92650 | DeepSeek V4 Flash | all (22 llamadas — corrida on-demand cloud, gcloud scheduler jobs run manual) | 46985 | 0.0087 | 0.0294 | 149.9706 |
| 2026-07-03 | ccec96c6 | DeepSeek V4 Flash | all (22 llamadas — corrida DUPLICADA, solapó con el trigger manual; ejecutó BUY SOL/USDT $0.03 real; cae bajo línea diaria pre-autorizada) | 64547 | 0.0120 | 0.0414 | 149.9586 |
| 2026-07-03 | cfddb499 | DeepSeek V4 Flash | all (22 llamadas — corrida de verificación post-fix HF offline, gateada; sin 429, pesos desde caché) | 46903 | 0.0087 | 0.0501 | 149.9499 |
| 2026-07-03 | calibrate-20260703T184804 | DeepSeek V4 Flash | calibración F6 (gateada $0.18): 6 símbolos, 20 fechas LLM, 360 llamadas → Kelly=0.10 confirmado, loss_limit 0.04 (intentos previos $0: env sin key) | 494543 | 0.0909 | 0.1410 | 149.8590 |
| 2026-07-03 | 29cb1a50 | DeepSeek V4 Flash | all (22 llamadas — 1ra corrida LIVE forzada, budget wallet $566.07; BUY SOL $430 rebotó por bolsillo USDT insuficiente — hallazgo pockets, $0 movido) | 55373 | 0.0102 | 0.1512 | 149.8488 |
| 2026-07-03 | c385db10 | DeepSeek V4 Flash | all (22 llamadas — corrida live v6, gate consolidado: cap por bolsillo OK ($366.99) pero market post-cancel rebotó 0379 (carrera de reserva) — $0 movido, fix en PR #27) | 54174 | 0.0101 | 0.1613 | 149.8387 |
| 2026-07-03 | c08a55c2 | DeepSeek V4 Flash | all (22 llamadas — corrida final v7 con fix carrera: verdict HOLD 80% → FREEZE correcto, 0 órdenes; pipe live validado end-to-end, $0 trading) | 49597 | 0.0092 | 0.1705 | 149.8295 |
| 2026-07-04 | 4da7d525 | DeepSeek V4 Flash | all (22 llamadas — 1ra corrida daily LIVE 100% autónoma, Scheduler 14:10Z: guard/wallet $565.82/pockets OK; BUY SOL $366.99 REJECTED 0379 (retry PR#27 se quedó corto — reserva >10s), $0 movido; línea diaria pre-autorizada) | 51087 | 0.0095 | 0.1800 | 149.8200 |
