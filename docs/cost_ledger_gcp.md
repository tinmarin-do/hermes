# Cost Ledger — Hermes GCP

Presupuesto total GCP (POC): **$10.00 USD**.
Cada fila representa una operación con costo real autorizada explícitamente vía `/cost:gate`.
**No editar manualmente** — solo vía `/cost:log`.

| fecha | recurso/operación | costo estimado (USD) | autorizado por | acumulado (USD) | restante |
|-------|-------------------|----------------------|----------------|-----------------|----------|
| — | — | — | — | 0.00 | 10.00 |
| 2026-07-03 | bootstrap: bucket tfstate hermes-tfstate-arctic-odyssey-501301-g0 (us-central1, versioning) + 8 APIs | ≤0.02/mes | Erika (gate interactivo) | 0.00 | 10.00 |
| 2026-07-03 | terraform apply full-stack: Cloud SQL db-f1-micro (~$8.60/mes) + Run×2 + Scheduler + 5 secrets + AR repo (14 recursos) | ~9.00/mes | Erika (gate interactivo — eligió full-stack con costo a la vista) | ~9.00/mes | ~1.00 |
