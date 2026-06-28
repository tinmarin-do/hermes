# Hermes — Claude Code Instructions

## Qué es Hermes
Sistema multiagente de trading con IA. Múltiples agentes LLM (LangGraph) colaboran para
decidir operaciones sobre criptoactivos, ejecutadas automáticamente en Binance. Desplegado
en GCP con Terraform. **Proyecto experimental y educativo — no asesoría financiera.**

## Modo de ejecución (`HERMES_MODE`)

| Modo | LLM | Base de datos | Exchange | Infra |
|------|-----|---------------|----------|-------|
| `local` | DeepSeek V4 Flash (API) | DuckDB (archivo local) | Paper (simulado) | Docker Compose |
| `cloud` | API hosted (DeepSeek/GPT) | Cloud SQL (Postgres) | Binance testnet/live | GCP + Terraform |

Siempre leer `HERMES_MODE` en `.envrc` antes de cualquier operación. Por defecto: `local`.

## Reglas críticas (no negociables)

1. **NUNCA** ejecutar operaciones GCP sin pasar primero por `/cost:gate`.
2. **NUNCA** hacer `terraform apply` sin `/infra:plan` antes.
3. **NUNCA** commitear secretos — Secret Manager (cloud) o `.env` local (en .gitignore).
4. **NUNCA** operar en modo live sin guardrails activos (Kelly + VaR + correlación).
5. **NUNCA** editar `docs/cost_ledger_*.md` manualmente — solo vía `/cost:log`.
6. **NUNCA** saltar `/cost:gate` aunque el costo estimado sea $0.00.
7. **NUNCA** ejecutar `gcloud` ad-hoc sin pasar por `/infra:gcloud`.

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

```bash
uv run pytest tests/unit/           # sin dependencias externas
uv run pytest tests/integration/    # requiere BINANCE_TESTNET_* en .env
uv run pytest tests/e2e/            # pipeline completo, paper mode
```

CI bloquea en: tests + cost-check + security scan.

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
