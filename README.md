# Hermes — Multi-Agent AI Trading System

> **Disclaimer:** Proyecto experimental y educativo. No constituye asesoría financiera.
> Opera únicamente con capital de riesgo que se puede perder por completo.

Hermes es una "firma de trading" simulada por **múltiples agentes LLM** que colaboran y
debaten para tomar decisiones sobre criptoactivos, ejecutadas automáticamente en Binance.
Corre 24/7 en GCP, mantiene un track record auditable y se expone en un dashboard público.

---

## Por qué existe

Los proyectos de portafolio típicos demuestran una competencia. Hermes demuestra cuatro:

| Competencia | Cómo se evidencia |
|-------------|------------------|
| **IA agéntica** | Pipeline LangGraph: RegimeClassifier → Analysts → Debate → Trader → Risk → PM |
| **Cloud / MLOps** | GCP provisionado con Terraform; CI/CD GitFlow; costo por corrida visible |
| **Full-stack** | Dashboard público (FastAPI + Jinja2 + Chart.js + htmx) siempre disponible |
| **Fintech cuantitativo** | Kelly sizing, VaR pre-trade, PSR, Sharpe bayesiano, Sortino, max drawdown |

---

## Arquitectura

```
ccxt (mercado) ──▶ Bronze (raw OHLCV)
                       ↓
                  Silver (Hurst + GARCH + spread)
                       ↓
                  Gold (régimen clasificado)
                       ↓
         ┌─────────────────────────────────┐
         │  Pipeline multiagente (LangGraph)│
         │  RegimeClassifier               │
         │  QuantCore (LightGBM+GARCH+Kelly)│  ← decide dirección/tamaño (sin LLM)
         │  Analysts ×3 (condicionados)    │
         │  Debate alcista/bajista         │
         │  Trader → Risk (VaR + Kelly)    │
         │  Allocator (pesos por símbolo)* │  ← reparte el budget entre los 6
         │  Portfolio Manager              │
         └──────────────┬──────────────────┘
                        ↓
              ExecutionAdapter (paper | testnet | live)
                        ↓
              Postgres / DuckDB  ←→  Dashboard público
```

**Principio clave:** cada capa vive detrás de una interfaz agnóstica.
Cambiar Binance por Alpaca (acciones) = implementar el adapter, sin tocar el cerebro.

> `*` **Allocator** = diseño aprobado, **pendiente de implementación**. Reparte un budget de
> trading entre los 6 símbolos como cartera (`conf × inverse-vol`), rebalanceado a diario.
> Hoy el motor es *winner-takes-all* (una sola apuesta). Ver `docs/DESIGN_portfolio_allocator.md`.

---

## Modos de ejecución

| | `HERMES_MODE=local` | `HERMES_MODE=cloud` |
|---|---|---|
| LLM | DeepSeek V4 Flash (API) | DeepSeek + GPT |
| Base de datos | DuckDB (archivo local) | Cloud SQL (Postgres) |
| Exchange | Paper (simulado) | Binance testnet / live |
| Infra | Docker Compose | GCP + Terraform |
| Costo | **$0** | ≤ $50 POC total |

---

## Inicio rápido (modo local — $0)

```bash
# Prerequisitos: Docker, uv, direnv
direnv allow && uv sync --extra dev

# Levantar stack (DuckDB + dashboard)
# Escribe en Claude Code:
/infra:local-up

# Cargar datos históricos
/data:backfill BTC/USDT 1h 2025-01-01 2026-06-01

# Primera corrida del pipeline
/hermes:run --local
```

Dashboard disponible en `http://localhost:8080`.

---

## Skills (slash commands)

El harness expone **34 skills atómicos** organizados por namespace:

```
/hermes:run          ← orquestador lean (entry point principal)

/cost:quote          /cost:gate           /cost:status
/infra:bootstrap     /infra:plan          /infra:apply
/infra:local-up      /infra:local-down    /infra:gcloud

/data:ingest-bronze  /data:transform-silver  /data:aggregate-gold
/data:backfill       /data:validate-*

/agents:run          /agents:debug        /agents:status
/execution:backtest  /execution:paper     /execution:live
/execution:kill      /execution:status

/test:unit           /test:integration    /test:e2e
/dashboard:build     /dashboard:deploy
/ops:health          /ops:logs
```

Ver `CLAUDE.md` para la referencia completa.

---

## Guardrails de riesgo

Ninguna orden se ejecuta sin pasar por el Risk agent:

- **Kelly fraccional** — sizing basado en confianza del PM y volatilidad actual (0.10 calibrado)
- **VaR pre-trade** — rechaza si pérdida 2σ excede el límite diario
- **Correlación** — rechaza si corr > 0.7 con posiciones abiertas
- **Short ultra-conservador** — solo si `P ≤ 0.25` + conf ≥ 0.50 + régimen bajista; **cap 10%** del budget; futuros-only en real; **OFF por default en live** (diseño, ver `docs/DESIGN_portfolio_allocator.md`)
- **Kill switch** — cierra todo en < 5 segundos vía `/execution:kill`
- **Keys sin retiro** — las API keys de exchange nunca tienen permiso de withdrawal

---

## Métricas de trading

Con muestra pequeña (< 60 trades), Hermes reporta:
- **PSR** (Probabilistic Sharpe Ratio) — ajusta por no-normalidad y tamaño muestral
- **Intervalo de credibilidad bayesiano** del Sharpe: `0.4 [90% CI: -0.8, 1.6]`
- **Sortino**, **max drawdown**, **win rate**, **profit factor**

El éxito del proyecto es el **proceso riguroso + la transparencia**, incluyendo reportar pérdidas.

---

## Stack tecnológico

| Capa | Tecnología |
|------|-----------|
| Lenguaje | Python 3.12 |
| Pipeline agéntico | LangGraph (sobre LangChain) |
| LLMs | DeepSeek V4 Flash (todos los roles) |
| Datos / exchange | ccxt |
| Data warehouse local | DuckDB |
| Backend | FastAPI + Jinja2 + htmx |
| Base de datos cloud | Cloud SQL (Postgres 16) |
| Orquestación cloud | Cloud Run + Cloud Scheduler |
| Secretos | Secret Manager |
| IaC | Terraform |
| CI/CD | GitHub Actions (GitFlow) |
| Empaquetado | Docker + uv |

---

## Estructura del repo

```
hermes/
├── src/
│   ├── adapters/      # Interfaces MarketDataSource + ExecutionAdapter
│   ├── brain/         # Pipeline LangGraph + agentes
│   ├── data/          # Bronze / Silver / Gold
│   ├── execution/     # Adapters paper / testnet / live
│   └── dashboard/     # FastAPI + Jinja2
├── tests/             # unit / integration / e2e
├── terraform/         # IaC — todo el provisioning GCP
├── .claude/commands/  # 34 skills del harness
├── .agents/           # Contrato JSON Schema (interop multi-agente)
├── .github/workflows/ # CI/CD GitFlow
└── docs/              # PRD, requirements, cost ledgers
```

---

## Presupuestos

| Dimensión | Cap POC | Cap mensual (post-POC) |
|-----------|---------|----------------------|
| GCP infra | $10 USD | — |
| LLM tokens | $40 USD | $150 USD |
| **Total operativo** | **$50 USD** | — |

El dashboard muestra `$$ gastado / $$ restante` en tiempo real.
Al alcanzar el cap de LLM, las corridas se pausan automáticamente.

> **Capital de trading** (bolsillo distinto del operativo): **$1 imaginario** en paper local,
> **$50 reales** en cloud al despegar. Ver `docs/DESIGN_portfolio_allocator.md`.

---

## Roadmap

- [ ] **Semana 0:** Evaluar TradingAgents vs LangGraph nativo; primer backtest local
- [ ] **Semana 1:** Pipeline completo corriendo local sobre cripto (paper)
- [ ] **Semana 2:** ExecutionAdapter testnet + guardrails + corridas programadas
- [ ] **Semana 3:** Dashboard público desplegado en GCP con Terraform
- [ ] **Semana 4:** Flip a live mínimo + panel MLOps + README/case study

**Post-MVP:** Acciones vía Alpaca · Integración con Odysseus UI

---

*Hermes — dios del comercio y los mensajeros.*
