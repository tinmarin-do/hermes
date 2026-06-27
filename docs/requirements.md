# Requirements — Hermes

## 1. Entorno de desarrollo local

| Requisito | Versión mínima | Notas |
|-----------|---------------|-------|
| Python | 3.12 | Requerido por `pyproject.toml` |
| uv | latest | Gestor de paquetes y entornos |
| Docker + Docker Compose | 24.x | Stack local completo |
| direnv | 2.32+ | Carga automática de `.envrc` |
| git | 2.40+ | GitFlow |
| terraform | 1.9+ | Solo para `HERMES_MODE=cloud` |
| gcloud CLI | latest | Solo para `HERMES_MODE=cloud` |

### Setup inicial (local)
```bash
# 1. Clonar y configurar entorno
direnv allow
uv sync --extra dev

# 2. Copiar y completar secretos
cp .env.example .env

# 3. Levantar stack local
/infra:local-up
```

---

## 2. Dependencias Python

Gestionadas en `pyproject.toml`. Instalación: `uv sync`.

### Core
| Paquete | Versión | Propósito |
|---------|---------|-----------|
| `ccxt` | ≥ 4.3 | Conectividad con 100+ exchanges |
| `duckdb` | ≥ 1.1 | Data warehouse local (modo `local`) |
| `pandas` | ≥ 2.2 | Manipulación de datos |
| `numpy` | ≥ 2.0 | Cómputo numérico |
| `arch` | ≥ 7.0 | Estimación GARCH(1,1) |
| `hurst` | ≥ 0.0.5 | Cálculo de Hurst exponent |
| `lightgbm` | ≥ 4.0 | Predictor direccional/edge del **núcleo de decisión** (gradient boosting sobre features tabulares) |
| `shap` | ≥ 0.45 | Interpretabilidad de features del LightGBM |
| `scipy` | ≥ 1.14 | Cópula t-Student (Risk Agent, Sprint 2); distribuciones estadísticas |
| `langgraph` | ≥ 0.2 | Orquestación del pipeline multiagente |
| `langchain-core` | ≥ 0.3 | Abstracciones LLM |
| `langchain-openai` | ≥ 0.2 | Adapter OpenAI/DeepSeek compatible |
| `fastapi` | ≥ 0.115 | Backend del dashboard |
| `uvicorn` | ≥ 0.32 | Servidor ASGI |
| `jinja2` | ≥ 3.1 | Templates del dashboard |
| `pydantic` | ≥ 2.9 | Validación de schemas |
| `structlog` | ≥ 24.4 | Logging estructurado |

### Cloud (extra: `uv sync --extra cloud`)
| Paquete | Propósito |
|---------|-----------|
| `google-cloud-secret-manager` | Acceso a secretos en GCP |
| `sqlalchemy` + `psycopg` | ORM + driver Postgres (Cloud SQL) |

### Dev (extra: `uv sync --extra dev`)
| Paquete | Propósito |
|---------|-----------|
| `pytest` + `pytest-asyncio` | Testing |
| `pytest-cov` | Cobertura de código |
| `ruff` | Linting + formatting |
| `mypy` | Type checking |
| `pip-audit` | Auditoría de vulnerabilidades |

### News clustering (extra: `uv sync --extra news`)
Sub-pipeline de clustering de eventos de noticias (ver PRD §8.7). Todo local, $0.
| Paquete | Propósito |
|---------|-----------|
| `sentence-transformers` | Embeddings de noticias (CPU, sin API) |
| `umap-learn` | Reducción de dimensión para clusterizar (inferencia reutilizable) |
| `hdbscan` | Clustering por densidad + métrica DBCV |
| `scikit-learn` | K-Means, Agglomerative, métricas de validez (silhouette, DB, CH) |
| `matplotlib` | Gráfica 2D (t-SNE) de inspección de clusters |

---

## 3. APIs externas requeridas

### Exchange — Binance
| Variable | Descripción | Cuándo se necesita |
|----------|-------------|-------------------|
| `BINANCE_TESTNET_API_KEY` | Key de testnet.binance.vision | Semana 2+ (integration tests) |
| `BINANCE_TESTNET_API_SECRET` | Secret de testnet | Semana 2+ |
| `BINANCE_API_KEY` | Key de producción (**solo-trade, SIN retiro**) | Semana 4 (live) |
| `BINANCE_API_SECRET` | Secret de producción | Semana 4 (live) |

> Obtener testnet keys en [testnet.binance.vision](https://testnet.binance.vision).
> Las keys de producción **NUNCA** deben tener permiso de retiro/withdrawal.

### LLMs (cloud mode)
| Variable | Modelo | Cuándo se necesita |
|----------|--------|-------------------|
| `DEEPSEEK_API_KEY` | DeepSeek V4 Flash (analysts, trader, risk) | `HERMES_MODE=cloud` |
| `OPENAI_API_KEY` | GPT-5.4 Mini (Portfolio Manager) | `HERMES_MODE=cloud` |

> En `HERMES_MODE=local` se usa Ollama — sin API keys.

### Noticias — CryptoPanic
| Variable | Descripción | Cuándo se necesita |
|----------|-------------|-------------------|
| `CRYPTOPANIC_API_KEY` | Key de [cryptopanic.com](https://cryptopanic.com/developers/api/) (tier gratuito) | Sprint 1 — sub-pipeline de clustering de noticias (§8.7) |

> El tier gratuito de CryptoPanic cubre el POC. Sin permisos sensibles.

### GCP (cloud mode)
| Requisito | Detalle |
|-----------|---------|
| Cuenta GCP activa | Con billing habilitado |
| Proyecto GCP | Crear antes de `/infra:bootstrap` |
| `gcloud auth login` | Autenticación previa en la máquina local |
| Rol mínimo | `roles/editor` en el proyecto |

---

## 4. Infraestructura GCP (cloud mode)

Provisionada íntegramente con Terraform. Ejecutar `/infra:bootstrap` → `/infra:apply`.

| Servicio | Uso | Tier / Config |
|---------|-----|---------------|
| Cloud Run | Dashboard + Brain (pipeline) | min-instances=0, scale to zero |
| Cloud SQL | Base de datos Postgres | `db-f1-micro`, Postgres 16 |
| Cloud Scheduler | Corridas automáticas cada 6h | 4 corridas/día |
| Secret Manager | API keys y credenciales | 7 secretos |
| Artifact Registry | Imágenes Docker | Repo Docker en `us-central1` |
| Cloud Build | CI/CD build de imágenes | Free tier (120 min/día) |

**APIs de GCP habilitadas por `/infra:bootstrap`:**
`cloudrun`, `sqladmin`, `cloudscheduler`, `secretmanager`, `artifactregistry`, `iam`, `logging`, `monitoring`

---

## 5. Requisitos funcionales por capa

### Capa de datos (Medallion)
- **RF-D1** Bronze: ingestar OHLCV crudo de ccxt para cualquier símbolo en `HERMES_ALLOWED_SYMBOLS`.
- **RF-D2** Bronze: detectar y reportar gaps temporales > 3× el timeframe.
- **RF-D3** Silver: calcular Hurst exponent (ventana 100 velas), GARCH(1,1), spread estimado.
- **RF-D4** Gold: clasificar régimen en `{trending, mean-reverting, volatile, illiquid}` con score de confianza.
- **RF-D5** Gold: snapshot debe tener < 2h de antigüedad antes de cada corrida de agentes.

### Capa de decisión (núcleo cuant + verificación agéntica)
- **RF-A1** Núcleo de decisión **cuantitativo y determinista**: régimen → LightGBM (dirección) → GARCH (sizing) → math de Risk (Kelly/VaR/correlación). Fija dirección y tamaño **sin LLM**; backtesteable con purged + embargoed walk-forward.
- **RF-A2** Pipeline agéntico (LangGraph) como **verificación**: RegimeClassifier → Analysts (×N) → Debate bull/bear (red-team) → Trader → Risk (×3) → PM. Los agentes solo pueden **vetar o recortar** la tesis cuant (freno asimétrico: opera en `[0, tamaño_cuant]`), **nunca originar ni amplificar**.
- **RF-A3** Cada corrida persiste: régimen, **señal cuant (LightGBM/GARCH)**, transcripción del debate, decisión y racional auditable.
- **RF-A4** El Risk agent ejecuta todos los guardrails antes de aprobar cualquier decisión.
- **RF-A5** **Validez de la capa agéntica (medible):** el backtest cuant-solo vs cuant+veto-agéntico debe mostrar mejora en Sharpe/drawdown; si no la muestra, la capa es decoración y se recorta.
- **RF-A6** Cada corrida registra tokens consumidos y costo USD en `cost_ledger_llm.md`.

### Capa de ejecución
- **RF-E1** ExecutionAdapter expone interfaz agnóstica: `paper | testnet | live`.
- **RF-E2** Guardrails no negociables (ver §6).
- **RF-E3** Toda orden se persiste con: símbolo, lado, size, fill price, fees, slippage, run_id.
- **RF-E4** Kill switch cierra posiciones en < 5 segundos y pausa el scheduler.

### Dashboard
- **RF-V1** Curva de equity, historial de trades, posición actual disponibles 24/7.
- **RF-V2** Visor de transcripción de debate para cada corrida.
- **RF-V3** Panel de métricas: Sharpe + PSR, Sortino, max drawdown, win rate.
- **RF-V4** Panel MLOps: costo por corrida, latencia, uptime, $$ gastado vs cap.
- **RF-V5** La página pública lee de snapshot (costo por visitante = $0).

---

## 6. Guardrails de riesgo (no negociables)

| Guardrail | Regla | Acción si viola |
|-----------|-------|-----------------|
| Kelly fraccional 0.25× | Size = f(confianza PM, volatilidad) | Rechazar orden |
| VaR pre-trade | 2σ loss ≤ límite diario | Rechazar orden |
| Correlación | corr > 0.7 AND exposición > límite | Rechazar orden |
| Pérdida diaria | ≤ `HERMES_DAILY_LOSS_LIMIT_PCT` del capital | Halt trading del día |
| Whitelist | Solo símbolos en `HERMES_ALLOWED_SYMBOLS` | Rechazar orden |
| Max posiciones | ≤ `HERMES_MAX_POSITIONS` abiertas | Rechazar orden |
| Keys sin retiro | API key no tiene permiso `withdrawal` | Bloqueo en setup |

---

## 7. Requisitos no funcionales

| Dimensión | Meta |
|-----------|------|
| Uptime dashboard | ≥ 99% en semana de evaluación |
| Latencia de corrida | Medida y visible en dashboard |
| Estabilidad pipeline | ≥ 7 días sin intervención manual |
| Reproducibilidad infra | `terraform apply` levanta entorno desde cero |
| Costo POC total | ≤ $50 USD (GCP $10 + LLM $40) |
| Costo LLM mensual (post-POC) | ≤ $150 USD |
| Seguridad | 0 secretos en el repo; 0 keys con permiso de retiro |
| Cobertura de tests | Unit tests sin deps externas; integration contra testnet |

---

## 8. Variables de entorno requeridas

Ver `.env.example` para la lista completa. Las mínimas para arrancar en `local`:

```bash
HERMES_MODE=local          # no requiere nada más para la primera corrida
```

Las mínimas para `cloud`:
```bash
HERMES_MODE=cloud
GCP_PROJECT_ID=<tu-proyecto>
TF_STATE_BUCKET=<bucket-tfstate>
DEEPSEEK_API_KEY=<key>
OPENAI_API_KEY=<key>
BINANCE_TESTNET_API_KEY=<key>
BINANCE_TESTNET_API_SECRET=<secret>
DATABASE_URL=<postgres-connection-string>
```
