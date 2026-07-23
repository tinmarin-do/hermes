# Hermes — Multi-Agent AI Trading System

> **Disclaimer:** Proyecto experimental y educativo. No constituye asesoría financiera.
> Opera únicamente con capital de riesgo que se puede perder por completo.

Hermes es dos cosas a la vez: un **overlay defensivo de momentum** sobre criptoactivos —
una señal cuantitativa determinista repartida como cartera, verificada por un equipo de
**agentes LLM (LangGraph) que actúan como red-team** (confirman, vetan o recortan; jamás
deciden el número) — y un **laboratorio de research anti-overfit** cuyo
[`EXPERIMENT_LOG`](docs/EXPERIMENT_LOG.md) documenta con método qué funciona y qué no
(4 hipótesis falsificadas antes de cualquier deploy). Corre 24/7 en GCP, mantiene un track
record auditable y se expone en un dashboard público.

> **Claim honesta (validada out-of-sample en un crash de −40%):** la señal desplegada no
> genera alpha absoluto — preserva capital en bear markets (+2.2% con la mitad del drawdown
> del mercado). El éxito del proyecto es el proceso riguroso, no un número de retorno.

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
         │  QuantCore (momentum multi-     │  ← decide dirección/tamaño (sin LLM)
         │   escala 7/14/30/90d + GARCH)*  │
         │  ── shadow: challenger regresión │  ← persiste, NO ejecuta (research)
         │  Analysts ×3 (condicionados)    │
         │  Debate alcista/bajista         │
         │  Trader → Risk (VaR + Kelly)    │
         │  Portfolio Manager              │
         │  Allocator (pesos conf×inv-vol) │  ← reparte el budget entre los 6
         └──────────────┬──────────────────┘
                        ↓
              ExecutionAdapter (paper | testnet | live)
                        ↓
              Postgres / DuckDB  ←→  Dashboard público
```

**Principio clave:** cada capa vive detrás de una interfaz agnóstica.
Cambiar Binance por Alpaca (acciones) = implementar el adapter, sin tocar el cerebro.

> `*` **Allocator implementado** (PR #10): reparte el budget entre los 6 símbolos como
> cartera (`conf × inverse-vol`, cap short 10%), rebalanceado a diario por delta vs libro.
> **QuantCore migra a la señal momentum multi-escala** (única validada en holdout — Fase 1
> del PRD v0.3); el LightGBM falsificado pasa a shadow. Pendiente: neteo del PaperAdapter
> (Fase 2) y vista de cartera (Fase 3). Ver `docs/HERMES_PRD.md` §9 y `docs/DESIGN_portfolio_allocator.md`.

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

- **Kelly fraccional** — sizing basado en confianza y volatilidad (interim 0.10; el valor definitivo sale de re-calibrar sobre la señal momentum — PRD §8.2)
- **VaR pre-trade** — rechaza si pérdida 2σ excede el límite diario
- **Correlación** — rechaza si corr > 0.7 con posiciones abiertas
- **Short ultra-conservador** — solo si `P ≤ 0.25` + conf ≥ 0.50 + régimen bajista; **cap 10%** del budget; futuros-only en real; **OFF por default en live** (diseño, ver `docs/DESIGN_portfolio_allocator.md`)
- **Kill switch** — cierra todo en < 5 segundos vía `/execution:kill`
- **Keys sin retiro** — las API keys de exchange nunca tienen permiso de withdrawal

---

## Métricas de trading

Con muestra pequeña (< 60 trades), Hermes reporta:
- **PSR** (Probabilistic Sharpe Ratio) — ajusta por no-normalidad y tamaño muestral
- **DSR** (Deflated Sharpe) — deflacta por número de configuraciones probadas (anti data-snooping)
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

## Roadmap (runbook por fases — PRD v0.3 §9)

- [x] **Base:** pipeline LangGraph 15 nodos + allocator de cartera + framework de research (PSR/DSR)
- [ ] **Fase 0:** higiene — whitelist XRP, alineación de guardrails, backfill
- [ ] **Fase 1:** señal momentum multi-escala en producción; LightGBM a shadow
- [ ] **Fase 2:** neteo del PaperAdapter (rebalanceo diario real)
- [ ] **Fase 3:** dashboard de cartera + panel champion vs shadow
- [ ] **Fase 4:** noticias P0 (multi-fuente + anti prompt-injection + clustering)
- [ ] **Fase 5:** deploy GCP (Terraform) + corridas diarias programadas
- [ ] **Fase 6:** testnet → live mínimo $50 (long-only, Kelly re-calibrado)

**Post-MVP:** challenger de regresión promovible · Acciones vía Alpaca · Odysseus UI

---

*Hermes — dios del comercio y los mensajeros.*
