# Cost Ledger — Hermes LLM (mensual)

Presupuesto LLM (POC sprint): **$40.00 USD** | Mensual post-POC: **$150.00 USD**.
Tope POC total (GCP $10 + LLM $40): **$50.00 USD**.
Cada fila representa una corrida de agentes autorizada. Se reinicia el día 1 de cada mes vía `/cost:reset-llm`.
**No editar manualmente** — solo vía `/cost:log`.

Referencia de precios (§11.2 PRD, junio 2026):
- RegimeClassifier + Analysts (×3): DeepSeek V4 Flash Free → $0.00/corrida
- Trader + Risk: DeepSeek V4 Flash → ~$0.01/corrida
- Portfolio Manager: GPT-5.4 Mini → ~$0.12/corrida
- **Costo base por corrida: ~$0.13** (free analysts) | ~$0.80 (modelos fuertes)
- **4 corridas/día → ~$15.60/mes** (conservador)

| fecha | corrida_id | modelo_pm | roles_pagados | tokens_totales | costo_usd | acumulado_mes (USD) | restante_mes (USD) |
|-------|------------|-----------|---------------|----------------|-----------|---------------------|--------------------|
| — | — | — | — | — | — | 0.00 | 150.00 |
