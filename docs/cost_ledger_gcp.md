# Cost Ledger — Hermes GCP

Presupuesto total GCP (POC): **$10.00 USD**.
Cada fila representa una operación con costo real autorizada explícitamente vía `/cost:gate`.
**No editar manualmente** — solo vía `/cost:log`.

| fecha | recurso/operación | costo estimado (USD) | autorizado por | acumulado (USD) | restante |
|-------|-------------------|----------------------|----------------|-----------------|----------|
| — | — | — | — | 0.00 | 10.00 |
| 2026-07-03 | bootstrap: bucket tfstate hermes-tfstate-arctic-odyssey-501301-g0 (us-central1, versioning) + 8 APIs | ≤0.02/mes | Erika (gate interactivo) | 0.00 | 10.00 |
| 2026-07-03 | terraform apply full-stack: Cloud SQL db-f1-micro (~$8.60/mes) + Run×2 + Scheduler + 5 secrets + AR repo (14 recursos) | ~9.00/mes | Erika (gate interactivo — eligió full-stack con costo a la vista) | ~9.00/mes | ~1.00 |
| 2026-07-03 | ajuste post-deploy (bajo paraguas full-stack): bucket estado hermes-state (~$0.01) + AR storage imágenes 4.3GB (~$0.43) + brain 2→4Gi por OOM (~$0.30 est) | +0.74/mes | Erika (paraguas full-stack; fila de reconciliación) | ~9.74/mes | ~0.26 |
| 2026-07-03 | fix HF_HUB_OFFLINE: build+push hermes-brain:v3 a AR (capa de modelo CACHEADA/idéntica a v2 — storage nuevo mínimo) + `gcloud run deploy` a revisión hermes-brain-00006-mnd (mismo 4Gi, $0 recurrente nuevo) | ~+0.02/mes est. (storage incremental, cotización peor-caso ~0.40-0.50 no se materializó por cache hit) | Erika (excedió cap explícitamente conociendo el detalle, luego realizado fue mucho menor) | ~9.76/mes | ~0.24 |
| 2026-07-03 | push v4 (Fase A) + v5 (F6) a AR — capas de modelo cacheadas, solo código (~MB) + deploys rev 00008/00011 + apply flip LIVE (EXCHANGE_MODE=live, budget wallet, loss limit 0.04 — solo env, sin recursos nuevos) | ~+0.01/mes | Erika (gates de la sesión F6; apply confirmado por ella) | ~9.77/mes | ~0.23 |
| 2026-07-04 | push AR brain:v8 + dashboard:v2 (1 capa de código c/u; v6/v7 de ayer fueron ~KBs ≈ $0 sin fila) + deploys rev 00014-5k4/00005-qrk $0 — PR #28: fix carrera 0379 + dashboard modo live + IAP declarado en TF | ~+0.01/mes | Erika ("Sí, dale" con cotización ~$0.00-0.02/mes a la vista) | ~9.78/mes | ~0.22 |
| 2026-07-04 | watchdog de drawdown (PRs #32-34): 2 jobs Scheduler (free tier) + canal email + alert policy log-match ($0) + rol custom + 3 IAM + dashboard v5-v7 a AR (capas código) — chequeo 30min ~48 wakeups/día 256Mi | ~+0.01/mes | Erika (plan mode aprobado con cotización ~$0.01/mes; drill 2 fases autorizado) | ~9.79/mes | ~0.21 |
