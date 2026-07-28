# Hermes — Sistema de trading multiagente **desplegado** + laboratorio de research anti-overfit

> **Disclaimer:** Proyecto experimental y educativo. No constituye asesoría financiera.
> Opera únicamente con capital de riesgo que se puede perder por completo.

**Esto no es un roadmap: está corriendo.** Hermes vive en GCP desde el 3 de julio de 2026 —
pipeline diario en Cloud Run, guardrails activos, dashboard detrás de IAP, órdenes reales
ejecutadas en dos venues. En paralelo corre un **laboratorio de research** que ha falsificado
y documentado **29 hipótesis contadas** (DSR) antes de dejar que ninguna toque dinero.

Hermes es dos productos en uno:

1. **Producción — overlay defensivo de momentum.** Una señal cuantitativa determinista
   (voto de signo multi-escala 7/14/30/90d) reparte un budget como **cartera** entre 6
   símbolos; un equipo de **agentes LLM (LangGraph) actúa como red-team** — confirman,
   vetan o recortan, **jamás deciden el número**. Ejecuta en **Bitso spot (long-only)**.
2. **Research — laboratorio anti-overfit 100% cloud.** Arcos de hipótesis pre-registrados
   con vara numérica fijada *antes* de correr, walk-forward purgado, PSR/Deflated Sharpe y
   holdout intocable. Todo el expediente — incluidos los fracasos — está en
   [`docs/EXPERIMENT_LOG.md`](docs/EXPERIMENT_LOG.md).

> **Claim honesta (validada out-of-sample en un crash de −40%):** la señal en producción
> **no genera alpha absoluto** — preserva capital en bear markets (+2.2% con la mitad del
> drawdown del mercado). El éxito del proyecto es el proceso riguroso y su trazabilidad,
> no un número de retorno.

---

## Estado real (28 de julio, 2026)

| Componente | Dónde vive | Estado |
|---|---|---|
| **Pipeline diario (comité + allocator)** | Cloud Run job + Cloud Scheduler `08:10` MX | **En producción** desde 2026-07-03 |
| **Ejecución live** | Bitso spot, long-only, budget **$400 USD** | **Activa** — primer trade real 2026-07-03 (BUY SOL $20.08, fee $0.07) |
| **Watchdog de drawdown** | Cloud Scheduler cada 30 min → re-corrida de emergencia | Activo |
| **Dashboard** | Cloud Run + **IAP (custom OAuth)** | **Privado por diseño** — `/api/live` sirve balances reales; demos = viewer temporal, no flip público |
| **Laboratorio de research** | Cloud Run job `hermes-lab` + bucket `hermes-research-*` | Activo; billing budget con alertas 50/80% |
| **Shadow (juez forward)** | Job `hermes-shadow` + scheduler; marks diarios | Activo — multi-stream, **jamás ejecuta** |
| **Ejecutor long-short** | Cloud Run job en `europe-west1`, Cloud NAT con IP fija, key IP-restringida | **Primer libro L/S real ejecutado 2026-07-13**: 6 órdenes, margen aislado 1x, fees reales $0.06 ≈ modelo |
| **Secretos** | Secret Manager (keys sin permiso de retiro) | Nunca en repo, nunca en contexto del agente |
| **CI/CD** | GitHub Actions (GitFlow): tests + cost-check + security scan | Verde como condición de merge |

**Costo real acumulado del arco de research en la nube: ~$17 de $290 de créditos** (regla
dura: jamás pasar del 80%). Cada operación con costo pasa por un gate de cotización.

---

## Por qué existe

Los proyectos de portafolio típicos demuestran una competencia. Hermes demuestra cuatro:

| Competencia | Cómo se evidencia |
|-------------|------------------|
| **IA agéntica** | Pipeline LangGraph de 15 nodos: RegimeClassifier → Analysts ×3 → Debate → Trader → Risk → PM, con el LLM como verificador y no como decisor |
| **Cloud / MLOps** | GCP con Terraform (Cloud Run, Scheduler, Cloud SQL, Secret Manager, IAP, NAT, billing budgets); imágenes versionadas; CI/CD GitFlow; costo por corrida visible |
| **Full-stack** | Dashboard FastAPI + Jinja2 + Chart.js + htmx tras IAP, con vista de cartera, gasto y track record |
| **Fintech cuantitativo** | Kelly fraccional, VaR pre-trade, PSR, Deflated Sharpe, Sharpe bayesiano, Sortino, max drawdown, walk-forward purgado + embargo |

Y una quinta, la que más cuesta encontrar: **disciplina anti-data-snooping**. Cada hipótesis
se pre-registra con su falsador *antes* de correr, y ningún resultado se re-interpreta
después ("no se ablanda la vara post-resultado").

---

## El registro de research (lo que casi nadie publica)

`n_trials = 29` contados para el Deflated Sharpe. Resumen del expediente:

| Arco | Hipótesis | Veredicto |
|---|---|---|
| **Exp. 0** | LightGBM direccional `P(ret_7d > 0)` sobre features de régimen | ❌ **Falsificado** — PSR 0.504 = moneda al aire; Sharpe 0.011 en 5.5 años |
| **H5–H6** | Regla momentum multi-escala como control no-ML | ✅ **Sobrevive** — demolió al ML; **es el champion desplegado** |
| **H7** | Logística regime-conditioned / cross-sectional (narrow y wide) | ❌ Falsificadas (3) |
| **H9–H10** | Regresión continua, carry/funding, taker imbalance, spreads OU, vol-targeting | ❌ **13 trials en un día, 0 promociones**. El vol-targeting sobrevive como capa de *riesgo*, no de alpha |
| **H11** | Clasificador binario diario en MXN (meta 1%/día) | ❌ Cerrado con veredicto: sin alpha a 1 día. El TP/SL fijo ±3% quedó **enterrado** (amputa la cola derecha) |
| **H12** | Barrido de horizontes + red neuronal (GRU vs TTM 805k params) | GRU h=28d pasa su one-shot; **TTM falsificado** — modelos pesados empeoran con SNR ~2% |
| **H13** | Retorno absoluto bidireccional: TSMOM long-short + arquetipos | TSMOM puro ❌ **falsificado 3/3**. El **spread L/S del GRU (`gruls-ivol`) PASÓ la vara §8.1** — primer pase de retorno absoluto del proyecto. Juez primario = shadow forward, sign-off pendiente |
| **H13 §14** | Watchdog de salida por precio (`k·sigma20`) | ❌ Falsificado 3/3 con **causa raíz identificada**: umbral de vol diaria contra camino acumulado de 28d (no escala con √t) |
| **H14** | Prima de rebalanceo ("cosecha del vaivén") sobre **825 perps** anti-supervivencia | 🔬 **Abierto** — pre-registrado, en fase EDA descriptiva (no cuenta al DSR) |

Detalles, tablas y caveats: [`docs/EXPERIMENT_LOG.md`](docs/EXPERIMENT_LOG.md) ·
diseños pre-registrados: [`docs/DESIGN_H13_trend_absolute.md`](docs/DESIGN_H13_trend_absolute.md),
[`docs/DESIGN_H14_rebalancing_premium.md`](docs/DESIGN_H14_rebalancing_premium.md).

Dos reglas de la casa que explican el tono del log:
- **Pre-registro obligatorio.** Grilla cerrada + falsador + vara numérica, commiteados antes
  de la primera corrida. Si el resultado no pasa, se documenta y se entierra.
- **Nada de verdict-shopping.** Un config que "apenas" supera un comparador blando no se
  reporta como ganador si falla la vara dura (pasó literalmente con `k=1.5` en §14).

---

## Arquitectura

Dos planos que **no se tocan entre sí** — el firewall del proyecto: el research jamás
modifica el pipeline vivo.

```
                      PLANO DE PRODUCCIÓN (vivo)
ccxt / Bitso ──▶ Bronze (OHLCV raw)
                     ↓
                Silver (Hurst + GARCH + spread + régimen)
                     ↓
                Gold (señales listas para agentes)
                     ↓
      ┌────────────────────────────────────────┐
      │  Pipeline multiagente (LangGraph)      │
      │  RegimeClassifier                      │
      │  QuantCore = regla momentum 7/14/30/90 │ ← decide dirección/tamaño (SIN LLM)
      │  Analysts ×3 → Debate → Trader         │ ← red-team: confirma / veta / recorta
      │  Risk (VaR + Kelly) → Portfolio Mgr    │
      │  Allocator (conf × inverse-vol)        │ ← reparte el budget entre los 6 símbolos
      │  Shadow: challengers persisten, NO ejecutan │
      └───────────────┬────────────────────────┘
                      ↓
        ExecutionAdapter (paper | Bitso spot live | Binance futures)
                      ↓
        Cloud SQL / DuckDB  ←→  Dashboard (FastAPI, tras IAP)


                      PLANO DE LABORATORIO (aislado)
corpus Binance (825 perps, point-in-time, anti-supervivencia)
        ↓
   src/lab/ → job `hermes-lab` (Cloud Run) → bucket `hermes-research-*`
        ↓                                          ↓
   window_check (40 ventanas 28d) + one-shot   experiments/trials.jsonl (DSR)
        ↓
   shadow forward (único juez 100% virgen) → sign-off humano → ejecutor L/S
```

**Principio clave:** cada capa vive detrás de una interfaz agnóstica. Cambiar de venue =
implementar el adapter, sin tocar el cerebro (ya pasó dos veces: Binance → Bitso spot →
Binance USDT-M futures).

---

## Guardrails de riesgo

Ninguna orden se ejecuta sin pasar por el Risk agent:

- **Kelly fraccional** — sizing por confianza y volatilidad (0.10, calibrado con
  `/brain:calibrate-risk` sobre la señal momentum)
- **VaR pre-trade** — rechaza si la pérdida 2σ excede el límite diario (loss limit 4%)
- **Correlación** — rechaza si corr > 0.7 con posiciones abiertas
- **Watchdog de drawdown** — revisión cada 30 min; dispara re-corrida del comité
- **Short ultra-conservador** — `P ≤ 0.25` + conf ≥ 0.50 + régimen bajista, cap 10%;
  requiere futuros, **OFF por default**. El live spot es long-only permanente
- **Kill switch** — cierra/pausa todo en < 5 s (`/execution:kill`)
- **Keys sin retiro** — nunca tienen permiso de withdrawal; la key de trading está
  restringida por IP a la del ejecutor
- **Firewall a dinero real** — ningún candidato de research toca capital sin: one-shot en
  slice con caveats documentados + shadow forward en el venue nuevo + sign-off humano +
  plomería en chiquito antes del tamaño completo

---

## Métricas de trading

Con muestra pequeña (< 60 trades), Hermes reporta:
- **PSR** (Probabilistic Sharpe Ratio) — ajusta por no-normalidad y tamaño muestral
- **DSR** (Deflated Sharpe) — deflacta por las 29 configuraciones probadas (anti data-snooping)
- **Intervalo de credibilidad bayesiano** del Sharpe: `0.4 [90% CI: −0.8, 1.6]`
- **Sortino**, **max drawdown**, **win rate**, **profit factor**
- **window_check** — 40 ventanas de 28d (seed 42) + corte temporal, para no confundir
  robustez con suerte de una ventana

---

## Modos de ejecución

| | `HERMES_MODE=local` | `HERMES_MODE=cloud` |
|---|---|---|
| LLM | DeepSeek V4 Flash (API) | DeepSeek / GPT hosted |
| Base de datos | DuckDB (archivo local) | Cloud SQL (Postgres 16) |
| Exchange | Paper (simulado) | Bitso spot live · Binance USDT-M futures |
| Infra | Docker Compose | GCP + Terraform |
| Capital de trading | $1 imaginario | $400 USD |
| Costo operativo | **$0** | ~$17 gastados de $290 en créditos |

### Inicio rápido (modo local — $0)

```bash
# Prerequisitos: Docker, uv, direnv
direnv allow && uv sync --extra dev

# Levantar stack (DuckDB + dashboard) — desde Claude Code:
/infra:local-up

# Cargar datos históricos
/data:backfill BTC/USDT 1h 2025-01-01 2026-06-01

# Primera corrida del pipeline
/hermes:run --local
```

Dashboard local en `http://localhost:8080`. El modo local no toca la nube ni dinero real.

---

## Skills (slash commands)

El harness expone **39 skills atómicos** organizados por namespace — el proyecto se opera
conversando con Claude Code, no con scripts sueltos:

```
/hermes:run          ← orquestador lean (entry point principal)

/cost:quote          /cost:gate           /cost:status        /cost:log
/infra:bootstrap     /infra:plan          /infra:apply        /infra:teardown
/infra:local-up      /infra:local-down    /infra:gcloud       /infra:state

/data:ingest-bronze  /data:transform-silver  /data:aggregate-gold
/data:backfill       /data:ingest-news       /data:validate-*

/agents:run          /agents:debug        /agents:status      /brain:calibrate-risk
/execution:backtest  /execution:paper     /execution:live     /execution:kill

/test:unit           /test:integration    /test:e2e
/dashboard:build     /dashboard:deploy    /ops:health         /ops:logs
```

Cada operación con costo pasa por `/cost:gate` y queda en un ledger que **no se edita a
mano**. Ver [`CLAUDE.md`](CLAUDE.md) para la referencia completa y las reglas no negociables.

---

## Stack tecnológico

| Capa | Tecnología |
|------|-----------|
| Lenguaje | Python 3.12 (ruff + mypy en CI) |
| Pipeline agéntico | LangGraph (sobre LangChain) |
| LLMs | DeepSeek V4 Flash (todos los roles) |
| Research / modelos | NumPy, pandas, scikit-learn, PyTorch (GRU), LightGBM (falsificado, en shadow) |
| Datos / exchange | ccxt · data.binance.vision (corpus histórico) · Bitso API |
| Warehouse | DuckDB (local) · Cloud SQL Postgres 16 (cloud) · GCS (bucket de research) |
| Backend | FastAPI + Jinja2 + htmx + Chart.js |
| Cómputo cloud | Cloud Run (services + jobs) · Cloud Scheduler · Cloud NAT con IP fija |
| Secretos / acceso | Secret Manager · IAP (custom OAuth) |
| IaC | Terraform (módulos: cloud-run, cloud-scheduler, secret-manager, monitoring, research-lab) |
| CI/CD | GitHub Actions (GitFlow) |
| Empaquetado | Docker + uv |

---

## Estructura del repo

```
hermes/
├── src/
│   ├── adapters/      # Interfaces MarketDataSource + ExecutionAdapter
│   ├── brain/         # Pipeline LangGraph, agentes, señal champion, shadow
│   ├── data/          # Bronze / Silver / Gold
│   ├── execution/     # Adapters: paper, Bitso spot, Binance futures, kill switch
│   ├── lab/           # Laboratorio de research (corre en GCP, aislado del brain)
│   └── dashboard/     # FastAPI + Jinja2 tras IAP
├── tests/             # unit (default, offline, $0) / integration / e2e
├── terraform/         # IaC — todo el provisioning GCP
├── research/          # Specs de experimentos
├── .claude/commands/  # 39 skills del harness
├── .agents/           # Contrato JSON Schema (interop multi-agente)
├── .github/workflows/ # CI/CD GitFlow
└── docs/              # PRD, EXPERIMENT_LOG, diseños pre-registrados, cost ledgers
```

### Testing

**342 tests unit verdes** (offline, $0), más suites de integración y e2e detrás de marker:

```bash
uv run pytest                  # SOLO unit — offline, sin costo (default seguro)
uv run pytest -m integration   # Binance testnet (requiere keys)
uv run pytest -m e2e           # pipeline completo, paper mode — PAGA LLM: cotizar antes
```

Las suites que cuestan dinero están deseleccionadas por marker: hay que pedirlas a propósito.

---

## Presupuestos

| Bolsillo | Cap | Estado |
|---|---|---|
| GCP infra (POC) | $10 USD | Sustituido en el arco de research por créditos + billing budget |
| Créditos de research GCP | $290 (regla dura: nunca > 80% = $232) | ~$17 gastados |
| LLM tokens | $40 POC · $150/mes post-POC | Ledger activo; al llegar al cap, las corridas se pausan solas |
| **Capital de trading** (bolsillo distinto) | $1 imaginario en paper · **$400 USD** en cloud | Live long-only en Bitso |

---

## Qué sigue

- Madurar los marks del **shadow forward** del candidato `gruls-ivol` → paquete de sign-off
  → cartera long-short completa (requiere ~$450–620 por los mínimos reales del venue)
- Terraformizar el stack EU del ejecutor (hoy creado por `gcloud`, drift documentado) y
  automatizar la reconciliación diaria
- Cerrar el arco **H14** (prima de rebalanceo) con su falsador pre-registrado — puede
  terminar falsificado, y eso también es un resultado válido

**Post-MVP:** challenger de regresión promovible · más símbolos con matriz de correlación ·
acciones vía Alpaca.

---

## Licencia

[PolyForm Noncommercial 1.0.0](LICENSE) — uso personal y no comercial.

*Hermes — dios del comercio y los mensajeros.*
