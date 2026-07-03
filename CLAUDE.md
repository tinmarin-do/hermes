# Hermes — Claude Code Instructions

## Qué es Hermes
**Overlay defensivo de momentum + laboratorio de research anti-overfit** (identidad v0.3,
2026-07-02). Una señal cuantitativa determinista (momentum multi-escala, única validada en
holdout) reparte un budget como cartera; agentes LLM (LangGraph) la **verifican como
red-team** (confirman/vetan/recortan — jamás deciden el número). El research continúa vía
shadow mode (challenger de regresión). Ejecuta en Binance, desplegado en GCP con Terraform.
**Proyecto experimental y educativo — no asesoría financiera.** La claim pública es honesta:
sin alpha absoluto; valor defensivo validado (`docs/EXPERIMENT_LOG.md`).
**Fuente de verdad de ejecución: `docs/HERMES_PRD.md` v0.3 — runbook §9, fases en orden.**

## Modo de ejecución (`HERMES_MODE`)

| Modo | LLM | Base de datos | Exchange | Infra |
|------|-----|---------------|----------|-------|
| `local` | DeepSeek V4 Flash (API) | DuckDB (archivo local) | Paper (simulado) | Docker Compose |
| `cloud` | API hosted (DeepSeek/GPT) | Cloud SQL (Postgres) | Binance testnet/live | GCP + Terraform |

Siempre leer `HERMES_MODE` en `.envrc` antes de cualquier operación. Por defecto: `local`.

## Portafolio y budget de trading (estado 2026-07-02)

Hermes reparte un **budget de trading** entre los 6 símbolos permitidos como **cartera**
(no una sola apuesta), **rebalanceado a diario**. Es un bolsillo **distinto** de los caps
operativos (GCP + LLM) de la sección Presupuestos.

| Entorno | Capital de trading | Naturaleza |
|---------|--------------------|------------|
| `local` / paper | **$1 imaginario** | Sandbox; día 0 arranca con $1 en cash. |
| `cloud` / real | **$50 USD reales** | Testnet primero; live solo con guardrails (regla #4). |

- **Whitelist (6):** BTC, ETH, SOL, **LINK**, AVAX, XRP (data `*/USDT` Binance). XRP reemplazó a MATIC (delistado); LINK reemplazó a BNB (no existe en **Bitso**, el venue de EJECUCIÓN decidido 2026-07-03 — data sigue de Binance; Bitso spot-only → live long-only permanente; fees 0.36% taker → preferir maker).
- **Pesos:** `conf × inverse-vol`, normalizados al budget. El delta vs el libro actual define buy/sell/hold.
- **Short:** ultra-conservador (`P ≤ 0.25` + conf ≥ 0.50 + régimen bajista; **cap 10%**). Futuros-only en real, simulado en paper, **OFF por default en live** (regla #8).
- **Kelly:** interim **0.10**; el definitivo sale de `/brain:calibrate-risk` sobre la señal momentum (PRD §8.2).
- **Estado:** allocator + capa de decisión **implementados** (PR #10). Pendiente (PRD §9):
  Fase 1 = migrar `quant_core` de LightGBM (falsificado) a la **regla momentum multi-escala**;
  Fase 2 = neteo del PaperAdapter; Fase 3 = vista de cartera en dashboard.
  Fuentes de verdad: PRD v0.3 §8.8/§9 y `docs/DESIGN_portfolio_allocator.md`.

## Reglas críticas (no negociables)

1. **NUNCA** ejecutar operaciones GCP sin pasar primero por `/cost:gate`.
2. **NUNCA** hacer `terraform apply` sin `/infra:plan` antes.
3. **NUNCA** commitear secretos — Secret Manager (cloud) o `.env` local (en .gitignore).
4. **NUNCA** operar en modo live sin guardrails activos (Kelly + VaR + correlación).
5. **NUNCA** editar `docs/cost_ledger_*.md` manualmente — solo vía `/cost:log`.
6. **NUNCA** saltar `/cost:gate` aunque el costo estimado sea $0.00.
7. **NUNCA** ejecutar `gcloud` ad-hoc sin pasar por `/infra:gcloud`.
8. **NUNCA** habilitar short en live sin opt-in explícito tras calibrar (`/brain:calibrate-risk`). Short real requiere venue de **futuros** (spot no puede); en paper se **simula**. Live arranca **long-only**. Ver §8.8 del PRD y `docs/DESIGN_portfolio_allocator.md`.

## Skills disponibles

### `hermes:*` — Orquestador lean (entry point principal)
| Command | Acción |
|---------|--------|
| `/hermes:run` | Pipeline completo de punta a punta — encadena todos los skills en orden |

### `cost:*` — Guardián de costos (base de todo)
| Command | Acción |
|---------|--------|
| `/cost:quote` | Estima costo de UNA operación sin ejecutar nada |
| `/cost:gate` | Muestra cotización + acumulado → pide autorización explícita |
| `/cost:log` | Append UNA entrada al ledger autorizado |
| `/cost:status` | Dashboard de gasto: GCP + LLM vs caps |
| `/cost:reset-llm` | Reinicia contador mensual LLM (día 1 de cada mes) |

### `infra:*` — Infraestructura (todos pasan por cost:gate)
| Command | Acción |
|---------|--------|
| `/infra:bootstrap` | Bootstrap GCP desde cero (bucket tfstate + APIs) |
| `/infra:plan` | `terraform plan` — solo lectura |
| `/infra:apply` | `terraform apply` con gate y log |
| `/infra:teardown` | Destruye recursos GCP con gate |
| `/infra:gcloud` | Ad-hoc `gcloud <cmd>` con cotización y gate |
| `/infra:state` | Estado actual de Terraform |
| `/infra:local-up` | Levanta stack local (Docker + DuckDB + dashboard) |
| `/infra:local-down` | Baja stack local |
| `/infra:local-status` | Estado del stack local |

### `data:*` — Medallion (Bronze → Silver → Gold)
| Command | Acción |
|---------|--------|
| `/data:ingest-bronze` | Pull OHLCV raw de ccxt para UN símbolo |
| `/data:validate-bronze` | Valida integridad de Bronze para UN símbolo |
| `/data:transform-silver` | Limpia + features de régimen para UN símbolo |
| `/data:validate-silver` | Valida Silver (Hurst, GARCH, spread calculados) |
| `/data:aggregate-gold` | Produce señales finales para agentes |
| `/data:validate-gold` | Valida Gold (señales completas, régimen clasificado) |
| `/data:backfill` | Relleno histórico para UN símbolo + rango |

### `agents:*` — Pipeline multiagente
| Command | Acción |
|---------|--------|
| `/agents:run` | Dispara UNA corrida completa del pipeline |
| `/agents:debug` | Inspecciona transcripción de UNA corrida por ID |
| `/agents:status` | Estado de la corrida activa o última |

### `brain:*` — Calibración y análisis
| Command | Acción |
|---------|--------|
| `/brain:calibrate-risk` | Backtest cuant + validación LLM para calibrar guardrails (Kelly, VaR, loss limit) |

### `execution:*` — Órdenes y posiciones
| Command | Acción |
|---------|--------|
| `/execution:backtest` | Backtest sobre histórico para UNA estrategia |
| `/execution:paper` | Envía UNA orden a paper/testnet |
| `/execution:live` | Envía UNA orden live (requiere confirmación extra) |
| `/execution:status` | Posiciones abiertas + P&L actual |
| `/execution:kill` | Kill switch — cierra/pausa todo inmediatamente |

### `ops:*` — Operaciones
| Command | Acción |
|---------|--------|
| `/ops:logs` | Tail de logs de UN servicio |
| `/ops:health` | Health check de todos los servicios |

### `dashboard:*` — Presentación
| Command | Acción |
|---------|--------|
| `/dashboard:build` | Genera assets del dashboard desde BD |
| `/dashboard:deploy` | Despliega dashboard a Cloud Run (con gate) |

### `test:*` — Testing
| Command | Acción |
|---------|--------|
| `/test:unit` | pytest tests/unit/ |
| `/test:integration` | pytest tests/integration/ (requiere Binance testnet) |
| `/test:e2e` | Pipeline completo en paper mode |

## Estructura del repo

```
hermes/
├── src/
│   ├── adapters/          # MarketDataSource, ExecutionAdapter (interfaces)
│   ├── brain/             # LangGraph pipeline, agentes, régimen
│   ├── data/
│   │   ├── bronze/        # Ingesta raw ccxt
│   │   ├── silver/        # Limpieza + features
│   │   └── gold/          # Señales para agentes
│   ├── execution/         # ExecutionAdapter implementations
│   └── dashboard/         # FastAPI + Jinja2 + Chart.js
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── terraform/             # IaC — todo el provisioning GCP
├── .claude/commands/      # Skills (este harness)
├── .agents/               # Contrato JSON Schema para agentes externos
├── .github/workflows/     # CI/CD GitFlow
├── docs/
│   ├── HERMES_PRD.md
│   ├── cost_ledger_gcp.md   # NO editar manualmente
│   └── cost_ledger_llm.md   # NO editar manualmente
├── docker-compose.yml       # Stack cloud-mode local
├── docker-compose.local.yml # Stack local-mode (DuckDB + dashboard)
├── pyproject.toml
└── .envrc
```

## Testing

Por default `pytest` corre SOLO unit (rápido, offline, $0). Las suites pagas/externas
(e2e invoca DeepSeek real ~$0.01/corrida; integration pega a Binance testnet) están
**deseleccionadas por marker** vía `addopts` — hay que pedirlas a propósito.

```bash
uv run pytest                       # SOLO unit (default seguro — sin red, sin costo)
uv run pytest -m integration        # Binance testnet — requiere BINANCE_TESTNET_* en .env
uv run pytest -m e2e                # pipeline completo, paper mode — PAGA LLM: cotizar
                                    #   + /cost:gate ANTES (regla #6). NO usar `pytest tests/`.
```

⚠️ NUNCA correr `pytest tests/` esperando “solo tests” — el marker filter del default lo
mantiene seguro, pero la suite paga se dispara con `-m e2e` explícito y nada más. Cotizá antes.

CI bloquea en: tests (`-m unit`) + cost-check + security scan.

## GitFlow

- `main` — producción (solo merge desde `release/*` o `hotfix/*`)
- `develop` — integración continua
- `feature/<nombre>` — nuevas features
- `hotfix/<nombre>` — fixes urgentes sobre main

PR hacia `develop` requiere: tests ✅ + cost-check ✅ + security scan ✅

## Presupuestos

| Dimensión | Cap POC | Cap mensual (post-POC) |
|-----------|---------|----------------------|
| GCP infra | $10 USD | — |
| LLM tokens | $40 USD | $150 USD |
| **Total POC** | **$50 USD** | — |

Al alcanzar el cap de LLM, `/agents:run` pausa automáticamente hasta el mes siguiente.
