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
