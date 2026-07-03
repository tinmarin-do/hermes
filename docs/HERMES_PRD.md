# PRD — Proyecto Hermes
### Overlay defensivo de momentum + laboratorio de research anti-overfit, con verificación multiagente

| | |
|---|---|
| **Autora** | Erika |
| **Rol** | Product & Tech Lead (solo) |
| **Versión** | 0.3 — Re-encuadre por evidencia (post arco de research H0–H8) |
| **Fecha** | 2 de julio, 2026 |
| **Estado** | Aprobado — este documento es el runbook de ejecución (§9) |
| **Codename** | *Hermes* (dios del comercio y los mensajeros) |

> **Disclaimer.** Hermes es un proyecto experimental y educativo. No constituye asesoría financiera ni de inversión. Opera únicamente con capital de riesgo que se puede perder por completo. El desempeño pasado no garantiza resultados futuros.

> **Cómo usar este documento.** El PRD es autosuficiente: §9 es el plan de ejecución fase por fase con criterios de aceptación — se avanza en orden y no se salta de fase sin cumplirlos. Las **fuentes de verdad** complementarias son:
>
> | Documento | Qué manda |
> |---|---|
> | `docs/EXPERIMENT_LOG.md` | Toda la evidencia de research (qué funciona, qué no, n_trials) |
> | `docs/DESIGN_portfolio_allocator.md` | Diseño detallado del allocator y la política de short |
> | `docs/calibration_report.md` | Calibraciones de guardrails (a re-correr, ver §8.2) |
> | `docs/cost_ledger_gcp.md` / `cost_ledger_llm.md` | Gasto real (NUNCA editar a mano — solo `/cost:log`) |
> | `CLAUDE.md` | Reglas críticas operativas y skills del harness |

---

## 1. Resumen ejecutivo (TL;DR)

Hermes es **dos productos en uno**, y la evidencia propia definió cuáles:

1. **Un overlay defensivo de momentum, desplegado de punta a punta.** La señal de producción es una **regla determinista de momentum multi-escala** (voto de signo en 7/14/30/90 días), repartida como **cartera** entre 6 símbolos por un allocator `confianza × inverse-vol`, con guardrails cuantitativos (Kelly, VaR, caps) y un equipo de **agentes LLM (LangGraph) que verifican como red-team** — confirman, vetan o recortan, **jamás deciden el número**. Su claim, validada out-of-sample en un crash real de −40%: **no genera alpha absoluto; preserva capital en bear markets** (quedó +2.2% con la mitad del drawdown del mercado).

2. **Un laboratorio de research anti-overfit.** Un framework de validación (purged + embargoed walk-forward, PSR/Deflated Sharpe, holdout reservado, shadow mode) que **cazó 4 falsos positivos antes de cualquier deploy** — LightGBM direccional, logística regime-conditioned y cross-sectional (narrow y wide) fueron **falsificados y documentados** en `EXPERIMENT_LOG.md`. El siguiente candidato (modelo de **regresión sobre variables continuas**) corre como *challenger* en shadow mode y solo se promueve si supera al champion con datos del futuro real (§8.9).

El objetivo de portafolio no cambió: una pieza que demuestre **cuatro competencias** — IA agéntica, cloud/MLOps, producto full-stack, y fintech cuantitativo. Lo que cambió (v0.3) es la **narrativa, ahora respaldada por evidencia**: no "mi ML le gana al mercado", sino *"construí el rigor que demuestra qué funciona y qué no, y desplegué exactamente lo que la evidencia soporta"*. Esa honestidad estadística **es** el diferenciador senior.

---

## 2. Problema y oportunidad

**Problema de portafolio.** Los proyectos típicos demuestran una competencia aislada. Para roles senior de IA/datos hace falta una pieza con criterio de producto **y** profundidad técnica **y** capacidad de llevar algo agéntico a producción.

**Oportunidad técnica.** El trading es ideal para sistemas multiagente (colaborativo por naturaleza, señal de calidad objetiva). Cripto ofrece datos gratis vía `ccxt`, mercado 24/7 y operabilidad desde México.

**Oportunidad de narrativa (nueva en v0.3).** El 99% de los proyectos de trading con IA venden un backtest inflado. Hermes vende lo contrario: un registro público de hipótesis falsificadas con método (López de Prado: PSR, DSR, purged walk-forward) y un deploy que solo afirma lo que sobrevivió un holdout intocado. Para un evaluador cuantitativo, **un `EXPERIMENT_LOG` con 4 falsificaciones honestas vale más que cualquier Sharpe de iteración.**

---

## 3. Objetivos, métricas y no-objetivos

### 3.1 Objetivos de producto
- **O1.** Sistema multiagente funcional de punta a punta: datos → decisión → ejecución → registro.
- **O2.** Desplegado y siempre vivo. **Dashboard PRIVADO por default** (IAM, decisión 2026-07-03); flip a público para demos = `terraform apply -var dashboard_public=true` (segundos, reversible).
- **O3.** Track record transparente y auditable (incluye el shadow challenger).
- **O4.** Que "hable solo" como evidencia de las 4 competencias.
- **O5 (nuevo).** Laboratorio de research activo con protocolo anti-overfit respetado al 100% (§8.9).

### 3.2 Métricas de éxito

| Dimensión | Métrica | Meta MVP |
|---|---|---|
| **Funcionalidad** | Pipeline completo corre sin intervención | ✅ corridas automáticas estables ≥ 7 días |
| **Confiabilidad** | Uptime del dashboard | ≥ 99% en la semana de evaluación |
| **Eficiencia (MLOps)** | Costo por corrida de agentes | ~$0.007 medido, visible en dashboard (§11.2) |
| **Latencia** | Tiempo de una corrida completa | Medido y mostrado; demo lee de caché |
| **Disciplina (fintech)** | Métricas ajustadas por riesgo | **PSR, DSR**, Sortino, max drawdown calculados y mostrados |
| **Disciplina (fintech)** | Respeto de límites de riesgo | 0 violaciones de caps/kill switch |
| **Rigor (research)** | Protocolo §8.9 respetado | EXPERIMENT_LOG al día; todo trial contado para DSR; 0 experimentos sin loguear |
| **Portafolio** | Legibilidad para un no-experto | Un reclutador entiende qué hace en < 60 s |

> **Nota técnica:** con muestra chica, Sharpe/Sortino son inestables. Hermes reporta siempre **PSR** (ajusta por no-normalidad y n) y **DSR** (deflacta por número de configuraciones probadas). Un PSR alto con DSR bajo = overfitting por selección.

### 3.3 Qué **no** es éxito (anti-métricas)
- ❌ Un número de rendimiento aislado ("hizo +X%") — ruido en muestra chica.
- ❌ "Ganarle al mercado" — no es el objetivo ni una promesa realista.
- ❌ **Vender el momentum como alpha** (dónde-no-ir #13 del EXPERIMENT_LOG): su valor probado es **defensivo** (protección de drawdown), no retorno absoluto. Toda comunicación del proyecto respeta esto.
- ✅ El éxito es el **proceso riguroso + la transparencia**, incluyendo reportar pérdidas y falsificaciones.

### 3.4 No-objetivos / Fuera de alcance (MVP)
- No es producto para terceros ni asesoría (regulación — ver §8.5).
- No soporta acciones en el MVP (roadmap, §12).
- No HFT ni microestructura. No onboarding/pagos/multi-tenant.

---

## 4. Usuarios y audiencia

| Audiencia | Tipo | Qué necesita ver |
|---|---|---|
| Reclutadores / hiring managers (IA, fintech, cloud) | Primaria | Que funciona, está desplegado, es sofisticado pero legible — y que la claim es honesta |
| Evaluadores del diploma | Primaria | Rigor técnico y de producto; el EXPERIMENT_LOG como evidencia de método |
| Erika (operadora) | Secundaria | Control, observabilidad, seguridad del capital |

---

## 5. Alcance funcional y prioridades

Notación: **P0** = imprescindible MVP · **P1** = mejora fuerte · **P2** = roadmap.

### 5.1 Capa de datos
- **P0** Ingesta OHLCV vía `ccxt` (Bronze → Silver → Gold). ✅ hecho.
- **P0** Features de régimen: Hurst, GARCH(1,1), spread. ✅ hecho.
- **P0** Sub-pipeline de noticias multi-fuente con scan de prompt injection (§8.7). ⏳ Fase 4.

### 5.2 Capa de decisión (núcleo cuant + verificación agéntica)
- **P0** **Clasificador de régimen** como primer paso (Hurst / GARCH / liquidez). ✅ hecho.
- **P0** **Núcleo de decisión cuantitativo y determinista — la señal champion:** la **regla de momentum multi-escala** (voto de signo 7/14/30/90d), única estrategia que sobrevivió el arco de research H0–H8 y el holdout (ver `EXPERIMENT_LOG.md`). Fija dirección por símbolo; el **allocator** (`conf × inverse-vol`) la convierte en pesos de cartera; GARCH y math de riesgo (Kelly/VaR) dimensionan. **Sin LLM en el camino numérico.** ⏳ Fase 1 (hoy `quant_core` aún corre el LightGBM falsificado — migrar es la primera tarea).
- **P0** **Shadow challenger:** el mejor **modelo de regresión para predicción de variables continuas** (no necesariamente LightGBM; selección por evidencia, §8.9) corre en paralelo **sin ejecutar órdenes**; sus decisiones hipotéticas se persisten y comparan contra el champion en el dashboard. Es la vía de research hacia alpha — si algún día lo hay, se demuestra con datos del futuro, no con backtest.
- **P0** **Capa de agentes LLM (LangGraph) como verificación**, no decisión: analistas → debate bull/bear (red-team) → trader → riesgo → PM. Confirman, vetan o recortan (`global_mult ∈ [0,1]`); **jamás originan dirección ni tamaño**. ✅ hecho (grafo de 15 nodos + allocator).
- **P0** **Allocator de cartera** (§8.8): pesos objetivo sobre los 6 símbolos, rebalanceo diario por delta vs libro. ✅ capa de decisión implementada (PR #10); ⏳ neteo del PaperAdapter (Fase 2).
- **P0** Persistir cada corrida: régimen, señales cuant, transcripción del debate, allocations, decisión final. ✅ hecho.
- **P1** Reflexión/aprendizaje entre corridas (memoria).

### 5.3 Capa de ejecución
- **P0** `ExecutionAdapter` agnóstico (`paper` → `testnet` → `live`). ✅ hecho.
- **P0** **Neteo/reciclaje de caja** en el PaperAdapter (hoy append-only: un SELL abre posición en vez de recortar — sin esto el rebalanceo diario no funciona de verdad). ⏳ Fase 2.
- **P0** Guardrails de riesgo (§8.2) + kill switch. ✅ hecho.
- **P0** Registro de órdenes y posiciones. ✅ hecho.

### 5.4 Capa de presentación (el showcase)
- **P0** Dashboard (privado por default, flip a público para demos — O2): equity curve, **vista de cartera** (pesos, P&L por símbolo, cash), historial, visor del debate, **panel champion vs shadow**. ✅ hecho (Fase 3); acceso del owner vía `gcloud run services proxy`.
- **P0** Panel de métricas: PSR, DSR, Sortino, drawdown. ⏳ Fase 3.
- **P0** IaC completa con Terraform (Cloud Run, Cloud SQL, Scheduler, Secret Manager, IAM). ✅ módulos escritos; ⏳ deploy Fase 5.
- **P1** Botón "correr análisis ahora" (rate-limited). P1 Panel MLOps (costo/latencia/uptime).
- **P2** Modo "explicación" para no técnicos.

### 5.5 Historias de usuario clave
- *Como reclutador*, abro la URL un domingo a medianoche y veo la cartera, la curva de equity y el debate — entiendo el proyecto sin que nadie me explique.
- *Como evaluadora cuant*, puedo leer el EXPERIMENT_LOG y verificar que ningún número desplegado viene de un backtest tuneado.
- *Como operadora*, defino límites de riesgo y puedo detener todo con `/execution:kill`.

---

## 6. Arquitectura técnica

```
                         ┌─────────────────────────────────┐
   Mercado (cripto) ───▶ │  CAPA DE DATOS                   │
   ccxt                  │  Bronze → Silver (Hurst/GARCH)   │
                         │  → Gold (+ noticias, Fase 4)     │
                         └──────────────┬──────────────────┘
                                        ▼
                         ┌─────────────────────────────────┐
                         │  CEREBRO (LangGraph, 15 nodos)   │
                         │  Regime → QuantCore              │
                         │  [señal = momentum multi-escala] │
                         │  → Analysts → Debate → Trader    │
                         │  → Risk → PM → ALLOCATOR         │
                         │  (pesos conf×inv-vol, cap short) │
                         │  ── shadow: challenger regresión │
                         │     (persiste, NO ejecuta) ──    │
                         └──────┬──────────────┬────────────┘
                                ▼              ▲
                         ┌─────────────────────────────────┐
                         │  CAPA DE EJECUCIÓN               │
                         │  vector de legs · neteo · paper  │
                         │  → testnet → live + GUARDRAILS   │
                         └──────┬──────────────┬────────────┘
                                ▼              ▲
        ┌───────────────────────────────────────────────────────┐
        │  ESTADO (DuckDB local / Cloud SQL)                    │
        │  decisiones · órdenes · posiciones · equity · costos  │
        │  · corridas shadow ← feedback: libro actual entra    │
        │    al estado ANTES del grafo (brain con estado)  →   │
        └───────────────┬───────────────────────────────────────┘
                        ▼
         FastAPI + Jinja2 + Chart.js ──▶ Dashboard público
```

**Estrategia de serving de LLM:** corridas programadas (no por visitante); la demo lee del historial; botón "correr ahora" rate-limited; DeepSeek V4 Flash unificado para todos los roles.

**Política de datos — local archiva, la nube opera (decidido 2026-07-03).** Con los parámetros de los modelos ya fijados (regla momentum, HDBSCAN del lab, UMAP persistido), la operación diaria NO necesita el histórico completo — necesita una **ventana rodante**: ~90 días de precios (la escala más larga del voto momentum es 2160h) + ~500h de warmup GARCH + noticias recientes + el track record (KBs/día, se conserva siempre). Por diseño:
- **LOCAL (DuckDB) = archivo de investigación** — histórico completo 2021→hoy ($0). Sin él no hay re-calibración de Kelly (F6), ni backtests del challenger, ni protocolo §8.9. **Jamás se poda.**
- **NUBE = operación** — solo la ventana rodante + track record + snapshot del dashboard. La base cloud es diminuta por diseño; el histórico nunca vive solo en la nube.

**Principios de diseño (sin cambios):** interfaces agnósticas (`MarketDataSource`, `ExecutionAdapter`); IaC total con Terraform — nada a mano en consola.

---

## 7. Stack tecnológico

| Capa | Tecnología |
|---|---|
| Lenguaje | Python 3.12 |
| Cerebro agéntico | **LangGraph nativo** (estructura de debate bull/bear inspirada en TradingAgents — decidido §13) |
| LLMs | DeepSeek V4 Flash (API hosted, unificado todos los roles) |
| Datos / ejecución | `ccxt` |
| Backend | FastAPI |
| Persistencia | DuckDB (local) / Cloud SQL Postgres (cloud) |
| Frontend | FastAPI + Jinja2 + Chart.js + htmx |
| Orquestación | Cloud Run + Cloud Scheduler |
| Secretos | Secret Manager |
| IaC | Terraform |
| CI/CD | Docker + GitHub Actions (GitFlow) |

---

## 8. Trading, riesgo y seguridad

### 8.1 Fases de operación
1. **Paper local** ($1 imaginario) — valida pipeline + señal + rebalanceo. **← estamos aquí.**
2. **Testnet** ($50 nominales) — valida ejecución real de órdenes.
3. **Live mínimo** ($400 reales — decisión 2026-07-03, antes $50) — solo con guardrails activos y calibrados, long-only al arranque.

### 8.2 Guardrails de riesgo (P0, no negociables)

- **Capital de trading:** **$1 imaginario** en paper local / **$400 USD** en cloud (decisión 2026-07-03: paper cloud corre a escala $400 YA para que el track record sea realista; live con ese monto solo tras F6 + calibración). Bolsillo **distinto** del cap operativo POC $50 = GCP $10 + LLM $40. `HERMES_CAPITAL_USD` es la única fuente del budget.
- **Kelly fraccional — CALIBRADO 2026-07-03** (`/brain:calibrate-risk` sobre la señal momentum multi-escala, 284 puntos semanales × 6 símbolos, grid 35 combos): **Kelly = 0.10** (el interim coincidió con el óptimo — F1 70.8%, recall 100%) y **daily loss limit = 0.04** (antes 0.02 default). Nota honesta: precision 54.8% ≈ moneda — consistente con la claim (valor defensivo, no alpha); el filtro aporta en las colas (avg return aprobados +1.28% vs rechazados −11.21%). Reporte: `docs/calibration_report.md`. El TBD queda cerrado; re-calibrar solo on-demand o por drift.
- **Pesos de cartera** en vez de apuesta única: `w_i ∝ conf_i / garch_vol_i`, normalizados al budget; `global_mult ∈ [0,1]` de los agentes solo puede reducir (§8.7.2).
- **VaR/CVaR pre-trade:** pérdida en escenario 2σ; si excede el límite, se rechaza.
- **Correlación:** corr > 0.7 con posiciones abiertas + exposición excedida → rechazo. *Sprint 2: cópula t-Student (crisis correlation).*
- **Límite de pérdida diaria** (2% del capital) → detiene la operación del día.
- **Kill switch** manual y automático (`/execution:kill`).
- **Whitelist de símbolos (6):** BTC, ETH, SOL, **LINK**, AVAX, XRP (notación de data: `*/USDT` de Binance). XRP reemplazó a MATIC (delistado, 2026-07-02); **LINK reemplazó a BNB** (no existe en Bitso, el venue de ejecución — decidido 2026-07-03; LINK = DeFi blue-chip, el menos correlacionado del cluster L1). `HERMES_MAX_POSITIONS=6`.
- **Short ultra-conservador** (§8.8): origen solo con `P ≤ 0.25` + conf ≥ 0.50 + régimen bajista; **cap 10% del budget**; futuros-only en real; simulado en paper; **OFF por default en live** (regla crítica #8).

### 8.3 Seguridad
- API keys **solo-trading, NUNCA withdrawal**. Secretos en Secret Manager / `.env` local (gitignored). Menor privilegio en GCP.

### 8.4 Evaluación honesta
- Toda claim de performance sale de: (a) el **EXPERIMENT_LOG** (backtests con protocolo §8.9), o (b) el **track record vivo** (paper/testnet/live + shadow). Nada más.
- Reportar **PSR, DSR, Sortino, max drawdown y P&L — incluyendo pérdidas** y experimentos fallidos.
- La claim pública del champion es exactamente esta: *"overlay defensivo de momentum; en el holdout (crash de −40%) quedó plano con la mitad del drawdown; su retorno absoluto no es estadísticamente distinguible de cero (PSR 0.585)"*.

### 8.5 Notas regulatorias y fiscales
- Hermes opera **capital propio** (automatización personal/educativa). Ofrecerlo a terceros = asesor de inversiones (CNBV en MX) — **fuera de alcance**.
- Ganancias/pérdidas cripto pueden tener implicaciones fiscales en México. Consultar a un profesional.

### 8.6 Modelos cuantitativos — estado por evidencia

| Modelo | Estado | Dónde vive | Evidencia / por qué |
|--------|--------|------------|---------------------|
| **Momentum multi-escala (regla, 7/14/30/90d)** | ✅ **CHAMPION** | `quant_core` (Fase 1) | Única sobreviviente de H0–H8. Holdout real (crash −40%): +2.2%, maxDD −27% vs −63% del mercado. Valor **defensivo**, no alpha. |
| **Regresión sobre variables continuas** | 🔬 **CHALLENGER (shadow)** | slot shadow del cerebro | Hipótesis nueva: predecir magnitud (retorno/vol futura) en vez de clasificar signo. Modelo a seleccionar por protocolo §8.9. No ejecuta hasta promoverse. |
| **GARCH(1,1)** | ✅ activo | Silver + allocator | Sizing inverse-vol. Pendiente: full-fit + propagación (de minutos a segundos). |
| LightGBM clasificador direccional | ❌ **FALSIFICADO** | solo EXPERIMENT_LOG | PSR(0)=0.504 en 5.5 años (moneda); perdió 3× contra reglas de una línea. Retirado del camino de decisión. |
| Logística regime-conditioned | ❌ FALSIFICADO | solo EXPERIMENT_LOG | Sharpe 0.43 vs 1.20 de la regla; explotó en 2024 (−52%). |
| Cross-sectional momentum (narrow y wide) | ❌ FALSIFICADO | solo EXPERIMENT_LOG | Spread market-neutral DSR 0.29→0.31 con 28 nombres; el long-only es beta disfrazada. |
| Cópula t-Student | 📋 Sprint 2 | guardrail de correlación | Pearson subestima correlación en colas (crisis correlation). |
| Ornstein-Uhlenbeck / Merton jump-diffusion | 📋 post-MVP | sizing / stops | Reversión explícita en mean-reverting; colas gordas para stops. |

**Dependencias:** `scipy`, `scikit-learn` (regresión challenger), `shap` (interpretabilidad).

### 8.7 Clustering de eventos de noticias (P0 — reconfirmado 2026-07-02)

**Motivación.** Hurst + GARCH capturan el *comportamiento estadístico* del precio; el clustering de noticias añade el *driver del evento* como señal ortogonal de **verificación** (nunca de origen — ver jerarquía §8.7.2). Además, el sub-pipeline es showcase NLP/seguridad por sí mismo.

**Ubicación medallion (sub-pipeline propio):**

```
Bronze:  Multi-fuente (CryptoPanic + editoriales RSS + Whale Alert) → raw + provenance → bronze_news
           → scanner de prompt injection (DeBERTa) marca cada noticia
Silver:  sentence-transformers (embeddings, local, $0)
           → UMAP → clustering (método por evaluación) → métricas de validez → silver_news_clusters
Gold:    news_cluster + news_sentiment_score + trust_score por símbolo → gold_signals
```

**Selección de método (no asumir HDBSCAN a priori):** arnés que compara K-Means / HDBSCAN / Agglomerative / DBSCAN con métricas no supervisadas (Silhouette, Davies-Bouldin, Calinski-Harabasz, DBCV). UMAP para reducir antes de clusterizar; t-SNE **solo** para la gráfica de inspección. Re-calibración **por drift** (fracción de outliers > umbral), no por corrida.

**Costo:** $0 (todo local/CPU, tiers gratuitos). **Dependencias (extra `news`):** `sentence-transformers`, `umap-learn`, `hdbscan`, `matplotlib`, `transformers`.

### 8.7.1 Modelo de amenaza — prompt injection y fake news

Hermes ejecuta órdenes con dinero: las noticias no confiables son superficie de ataque financiera.

**Invariante de diseño (regla de oro).** El texto crudo de una noticia **NUNCA entra a un LLM de decisión**. El sub-pipeline lo reduce a features categóricas (`news_cluster`, `news_sentiment_score`, `trust_score`, `injection_flag`) antes de Gold. Un enum no puede cargar un payload de inyección — control arquitectónico, no filtro frágil.

**Amenaza 1 — Prompt injection:** scanner off-the-shelf (`protectai/deberta-v3`) en Bronze marca `injection_flag`; las marcadas se excluyen y se loguean. Backstop: la regla de oro + guardrails.

**Amenaza 2 — Fake news:** no hay detector maduro; la defensa es **arquitectura**: multi-fuente de naturaleza distinta (CryptoPanic, CoinDesk/CoinTelegraph/Decrypt RSS, **Whale Alert on-chain** — la menos manipulable), `trust_score` por corroboración (≥2 fuentes) y reputación, propagado a Gold. **Las noticias entran al Risk agent y PM** (no al Analyst inicial): confirman o frenan un trade ya justificado por datos — **una noticia jamás convierte un HOLD en BUY**.

**Honestidad sobre límites:** fake news es problema abierto; se acota su impacto, no se promete resolverlo.

### 8.7.2 Jerarquía de decisión — datos → cuant → verificación LLM

**Principio (sin cambios, es el corazón de Hermes).** La señal se construye en orden de **confianza por verificabilidad**; el número lo fija la columna cuantitativa determinista:

```
1. Datos / Métricas   (OHLCV, Hurst, GARCH, spread)          → hechos duros, no manipulables
2. Decisión cuant     (régimen → momentum multi-escala →      → tesis DETERMINISTA y backtesteable
                       allocator conf×inv-vol → Kelly/VaR)      — sin LLM en el camino numérico
3. Verificación LLM   (debate bull/bear + noticias)           → red-team → CONFIRMA / VETA / RECORTA
```

**Por qué el núcleo es cuant y no agéntico.** Un LLM es no-determinista, no hace aritmética confiable, alucina confianza y **no se puede backtestear barato**. La columna que fija dirección y sizing es 100% cuantitativa y se valida con purged + embargoed walk-forward. *Construir el sistema multiagente y decidir deliberadamente que no decida el número es la postura de ingeniería que distingue a Hermes de un wrapper agéntico.*

**Asimetría = propiedad de seguridad (freno, nunca acelerador).** Los LLM pueden **vetar o recortar** (`global_mult ∈ [0,1]` hacia 0), **jamás originar ni amplificar**. Una alucinación solo puede costar **oportunidad**, nunca **capital**. El freno global ya está implementado: si risk rechaza o el verdict es HOLD → el libro se **CONGELA** (0 órdenes; nada nuevo se despliega). *Semántica corregida 2026-07-03: antes `global_mult=0` LIQUIDABA el libro entero — un día sin convicción vendía todo y pagaba fees de ida y vuelta. Congelar preserva la asimetría (el freno no origina trades, ni siquiera de salida); la liquidación de emergencia tiene su camino propio (`/execution:kill`), y las salidas ordinarias las originan las señales cuant en días con convicción.*

**Anti-manipulación.** El lenguaje es el eslabón más manipulable; al situarlo como verificación, una noticia falsa o un argumento alucinado no puede *originar* un trade — solo *frenar* uno que los datos ya justificaron.

### 8.8 Asignación de portafolio y short conservador ($1 → $400)

> **Estado (2026-07-02):** capa de decisión **IMPLEMENTADA y mergeada** (PR #10): nodo `allocator` determinista (pesos `conf × inverse-vol`, cap short 10% enforceado en código, delta vs libro), 6 señales por corrida, libro inyectado al estado antes del grafo, ejecución de vector de legs. **Pendiente:** neteo del PaperAdapter (Fase 2) y vista de cartera en dashboard (Fase 3). Detalle: `docs/DESIGN_portfolio_allocator.md`.

- **Mecanismo — rebalanceo por pesos objetivo.** Cada día: `quant_core` scorea los 6 → allocator normaliza a pesos `w_i ∝ conf_i / garch_vol_i` → ejecución = delta vs libro (objetivo > actual → BUY; < → SELL; ≈ → HOLD). Día 0 (todo cash) es el mismo mecanismo.
- **Short — ultra-conservador, data-first.** Origen: `P ≤ 0.25` + conf ≥ 0.50 + régimen bajista confirmado (si no → HOLD). Portero determinista en el allocator: **cap corto ≤ 10% del budget**. Freno LLM: el bear debe citar la evidencia cuant. **Venue (actualizado 2026-07-03): Bitso es spot-only → short real IMPOSIBLE → live es long-only PERMANENTE mientras el venue sea Bitso**; el short existe solo simulado en paper (calibra la política sin riesgo). Nota honesta del EXPERIMENT_LOG: el cap 10% implica que el short **no protege en bear markets** (2022 lo demostró) — es control de riesgo, no motor de retorno.
- **Cadencia diaria + gobernanza de costo.** Una corrida programada no puede pasar por `/cost:gate` interactivo (regla #6) → **pre-autorizar una línea de budget diario en el ledger** (~$0.007/día ≈ $0.21/mes vs cap $40); el cron consume contra ella y **se frena si la supera**. Este procedimiento se activa en Fase 5 (Cloud Scheduler).

### 8.9 Laboratorio de research — protocolo anti-overfit v2 (2026-07-02)

El protocolo v1 (holdout histórico intocable) cumplió su ciclo: el holdout `2025-06-28 → 2026-06-28` **se gastó una única vez** para validar al champion. Protocolo vigente:

1. **Ventana de iteración = toda la historia disponible** (2021 → 2026-06-28, holdout quemado absorbido). Ya no hay holdout histórico: el juez final es el futuro real.
2. **Juez final = track record en vivo (shadow/paper).** Datos del futuro no se pueden overfittear. Ningún candidato ejecuta órdenes por haber ganado un backtest.
3. **Pipeline de promoción de un candidato:**
   - *Backtest de iteración:* corte a priori **PSR(0) > 0.95 ∧ DSR > 0.90** + **stress obligatorio** (fees ≥ 10bps/lado, sensibilidad de parámetros vecinos, desglose por año). Si no pasa → se loguea y muere.
   - *Shadow mode:* **≥ 90 días** corriendo en paralelo persistiendo decisiones hipotéticas.
   - *Promoción:* supera al champion en la ventana shadow (Sharpe/PSR mayores, maxDD no peor) → reemplazo con opt-in explícito de la operadora, documentado en §13.
4. **Higiene (sin cambios de v1):** una variable por experimento · contar TODOS los trials para el DSR · no tunear umbrales sobre el test · todo experimento (incluidos fallidos) se loguea en `EXPERIMENT_LOG.md` con hipótesis/setup/resultado/conclusión · la lista "dónde NO ir" (15 puntos) es lectura obligatoria antes de proponer hipótesis nuevas.
5. **Backlog a priori del challenger de regresión:** targets continuos candidatos (retorno forward, vol realizada futura), labels triple-barrier (H1 del backlog), momentum 12-1 con skip-week (única bala a priori restante del arco momentum, dónde-no-ir #15).

---

## 9. Plan de ejecución — runbook por fases (reemplaza al sprint de 4 semanas)

> **Regla del runbook:** las fases se ejecutan **en orden**; no se pasa a la siguiente sin cumplir los criterios de aceptación. Toda operación con costo pasa por `/cost:quote` + `/cost:gate` ANTES (reglas #1 y #6, incluso si estima $0.00). Cada PR va a `develop` vía GitFlow con CI verde (unit + cost-check + security).

### Fase 0 — Higiene (inmediata)
**Objetivo:** cerrar el drift documental y de runtime que este PRD resuelve.
- [ ] Commitear los cambios pendientes en `develop` (H8/H8-wide en EXPERIMENT_LOG + `backtest.py` con crosssec, fix timezone y price cache) — rama `feature/*`, PR, CI verde.
- [ ] Alinear runtime: `.envrc` → `HERMES_ALLOWED_SYMBOLS` con **XRP/USDT** (fuera MATIC), `HERMES_KELLY_FRACTION=0.10` (interim), `HERMES_CAPITAL_USD=1` (paper), `HERMES_MAX_POSITIONS=6`. Alinear los **defaults hardcodeados** en `src/` que aún digan 500/0.25/2 (runner.py, quant_core.py, risk.py, allocator.py, pm.py) — recordar que direnv NO se engancha en bash no-interactivo.
- [ ] Backfill Bronze→Silver→Gold de XRP/USDT (bronze 2021→2026 ya existe por H8-wide; correr Silver+Gold).
- **Aceptación:** `uv run pytest` verde · `git status` limpio en develop · Gold fresco para los 6 símbolos de la whitelist nueva.

### Fase 1 — Señal honesta en producción
**Objetivo:** que el pipeline opere la señal validada, no la falsificada.
- [ ] Portar la regla momentum multi-escala de `backtest.py` a `quant_core` (o clase hermana `QuantRule`) emitiendo el mismo contrato (dirección + confianza por símbolo); el gate de short asimétrico (§8.8) se mantiene.
- [ ] Mover el LightGBM al **slot shadow** (persiste señales hipotéticas por corrida, no ejecuta) — es el placeholder del challenger hasta que exista el modelo de regresión.
- [ ] Tests unit del nuevo núcleo + e2e adaptado (e2e PAGA: cotizar + gatear antes, regla #6).
- **Aceptación:** `/agents:run` en paper produce 6 señales momentum + allocations coherentes · corrida shadow persistida en BD · unit verde, e2e verde gateada · EXPERIMENT_LOG anota el switch de señal.

### Fase 2 — Neteo del PaperAdapter (rebalanceo real)
**Objetivo:** que un SELL recicle caja en lugar de abrir posición nueva.
- [ ] Implementar posiciones netas por símbolo + reciclaje de caja en `src/execution/` (la lógica de delta del allocator ya está lista y testeada).
- [ ] Test de ciclo: día 0 (todo cash → BUYs) → día 1 con precios movidos (BUY/SELL/HOLD por delta) → equity y cash consistentes.
- **Aceptación:** dos corridas paper consecutivas rebalancean de verdad (el libro converge a los pesos objetivo) · suite unit verde.

### Fase 3 — Dashboard de cartera
**Objetivo:** el showcase visible.
- [ ] Vista de cartera: pesos actuales vs objetivo, P&L por símbolo, cash.
- [ ] Equity curve + PSR/DSR/Sortino/maxDD del track record paper.
- [ ] **Panel champion vs shadow** (equity hipotética del challenger vs real del champion).
- [ ] Visor de debate (ya existe base SHAP/FastAPI — completar TODOs de `build.py`).
- **Aceptación:** todos los endpoints 200 · un no-experto entiende la cartera en < 60 s · snapshot regenerable con `/dashboard:build`.

### Fase 4 — Noticias P0 (§8.7)
**Objetivo:** la capa de verificación enriquecida + showcase NLP/seguridad.
- [ ] Bronze: ingesta multi-fuente (`/data:ingest-news`) + scanner DeBERTa (`injection_flag`).
- [ ] Silver: embeddings → UMAP → arnés de clustering (4 candidatos, métricas de validez) → elección documentada.
- [ ] Gold: `news_cluster`, `news_sentiment_score`, `trust_score` por símbolo; cableo a Risk/PM (nunca al Analyst inicial ni texto crudo a ningún LLM).
- **Aceptación:** una noticia inyectada de prueba queda marcada y excluida · trust_score refleja corroboración multi-fuente · $0 de costo LLM · el debate cita features de noticias, no texto.

### Fase 5 — Deploy GCP
**Objetivo:** URL pública siempre viva.
- [ ] `/infra:bootstrap` → `/infra:plan` → `/cost:gate` → `/infra:apply` (reglas #1/#2/#7 SIEMPRE).
- [ ] Cloud Scheduler: 1 corrida diaria; **pre-autorizar la línea de budget diario en el ledger** (§8.8) para que el cron no viole la regla #6.
- [ ] Dashboard en Cloud Run (`/dashboard:deploy`); Cloud SQL vía Terraform; secretos a Secret Manager.
- **Aceptación:** URL pública ≥ 99% uptime en 7 días · corridas diarias automáticas estables · gasto GCP ≤ $10 POC visible en `/cost:status`.

### Fase 6 — Bitso stage → live mínimo ($400) *(venue 2026-07-03; monto 2026-07-03)*
**Objetivo:** ejecución real en **Bitso** (spot, cuenta MX de Erika) con guardrails calibrados.
- [ ] **BitsoAdapter** (ccxt `bitso`): mapping data→ejecución (`LINK/USDT` Binance-data → `LINK/USD` Bitso; AVAX→`AVAX/USD`; resto `*/USDT`), órdenes **maker/limit preferidas** (0.30% vs 0.36% taker — el stress a 36bps dio Sharpe 0.88 vs 1.20 a 10bps: sobrevive pero adelgaza).
- [ ] API key de Bitso **sin permiso de retiro** (§8.3), en `.env`/Secret Manager.
- [ ] Validar contra el **sandbox stage de Bitso** (ccxt lo soporta) — reemplaza al testnet de Binance.
- [ ] **Re-calibrar guardrails sobre la señal momentum** con `/brain:calibrate-risk` → fija el Kelly definitivo (cierra el TBD de §8.2) y actualiza `calibration_report.md`.
- [ ] Stage ≥ 7 días estables → flip a live **long-only permanente** (Bitso spot-only — el short queda solo en paper) con los $50.
- **Aceptación:** 0 violaciones de guardrails · kill switch probado · track record live alimentando el dashboard.

**Definición de "Hecho" (MVP):** Fases 0–5 completas + 7 días estables desplegado; señal champion operando; shadow persistiendo; EXPERIMENT_LOG al día; infra reproducible con `terraform apply`; README/case study con la narrativa honesta.

---

## 10. Instrumentación y observabilidad

Registrar y exponer: régimen detectado · señales cuant (champion **y** shadow) · transcripciones de debate · allocations y órdenes · curva de equity real e hipotética · **costo por corrida (tokens + USD, medido por `cost_meter`)** · latencia · uptime · violaciones de riesgo (debe ser 0) · gasto acumulado vs caps ($40 LLM POC / $10 GCP) · corridas con `logged_to_ledger=FALSE` (alerta de gap de gobernanza).

---

## 11. Riesgos y mitigaciones

### 11.1 Tabla de riesgos

| Riesgo | Prob. | Impacto | Mitigación |
|---|---|---|---|
| **El edge defensivo también decae** (momentum cripto post-2021 se agota — EXPERIMENT_LOG) | Media | Medio | La claim ya es defensiva, no de retorno; monitoreo del champion en vivo; challenger en shadow como reemplazo eventual |
| **Deriva narrativa** (volver a vender alpha que no existe) | Media | Alto (credibilidad) | §3.3 anti-métricas + §8.4: toda claim sale del EXPERIMENT_LOG o del track record vivo |
| Costo LLM se dispara | Baja | Alto | Medición real (~$0.007/corrida); corridas programadas; línea diaria pre-autorizada; pausa automática al cap |
| Overfitting por iteración del challenger | Media | Alto | Protocolo §8.9: DSR con todos los trials, stress obligatorio, shadow ≥ 90 días |
| Config GCP frágil | Media | Medio | Terraform IaC, todo versionado |
| Pérdidas en vivo | Alta | Bajo ($50) | Capital mínimo; framing = proceso; reportar con honestidad |
| Fuga de API key | Baja | Crítico | Keys solo-trade + Secret Manager |
| Scope creep | Alta | Alto | Runbook §9 estricto: en orden, con criterios de aceptación |

### 11.2 Modelo de costos LLM (medido, no estimado)

Realidad medida por `src/brain/cost_meter.py` (DeepSeek V4 Flash, $0.14/$0.28 por 1M tokens):

| Concepto | Valor real |
|---|---|
| Costo por corrida completa (18 llamadas, ~37K tokens) | **~$0.007** |
| 1 corrida/día (cadencia §8.8) | **~$0.21/mes** |
| 4 corridas/día (si se sube) | ~$0.83/mes |
| Calibración LLM | ~N_fechas × $0.007 |
| Backtest cuantitativo (sin LLM) | $0 |

> **Caps:** POC = **$40 LLM + $10 GCP = $50 total**. Post-POC: $150/mes LLM. El dashboard muestra gastado/restante; al alcanzar el cap, `/agents:run` se pausa hasta el mes siguiente. La estimación original del PRD v0.2 (~$0.24/corrida, ~$29/mes) estaba inflada ~34× — se corrigió con medición real.

---

## 12. Roadmap / trabajo futuro
- **Challenger de regresión** (§8.9): targets continuos + triple-barrier labels + momentum 12-1 skip-week.
- Cópula t-Student en el guardrail de correlación (Sprint 2).
- Acciones vía Alpaca (paga el diseño agnóstico). Odysseus UI. Memoria de largo plazo entre corridas. Modelos de régimen Markov-switching.

---

## 13. Registro de decisiones

**2026-07-03 (tarde — hardening Fase A):**
- **Capital de trading cloud: $50 → $400 USD** (decisión de Erika). Secuencia: el paper cloud pasa YA a escala $400 (track record realista, libro migrado era-$1→era-$400); **live con $400 reales solo tras Fase B**: key Bitso rotada+sin retiro confirmada → F6 BitsoAdapter (maker-first, sandbox stage) → `/brain:calibrate-risk` a escala $400 → días de stage. Reglas #4/#8 intactas.
- **Semántica del freno global: HOLD = CONGELAR, no liquidar** (§8.7.2). Hallazgo del 2026-07-03: el primer día HOLD cloud vendió toda la posición SOL solo por falta de convicción (churn/fees). El freno ahora emite 0 órdenes y el libro queda como está.
- **Guard anti-corrida-duplicada:** 1 corrida OK por día (`daily_run` rc=3 si ya corrió; override explícito `HERMES_FORCE_RUN=1` / `POST /run?force=true`). Origen: el Scheduler 08:10 MX y un trigger manual se solaparon el mismo día y el duplicado ejecutó un BUY.
- **Reserva de fees en el allocator** (`HERMES_FEE_RESERVE_PCT`, default 0.5%): el desplegable se recorta para que el último BUY del rebalanceo no rebote por fees (pendiente conocido de F2 que muerde a escala $400).

**2026-07-03:**
- **Exchange de EJECUCIÓN = Bitso** (decidido — Erika tiene cuenta fondeada + API; CNBV-regulado, rampa MXN). **La DATA sigue siendo Binance** (bronze 2021→2026, más profundo y líquido); el `ExecutionAdapter` mapea (el diseño agnóstico pagando su dividendo). Consecuencias: **LINK reemplaza a BNB** (no existe en Bitso) · fees 0.36% taker/0.30% maker → stress medido: Sharpe iteración 1.20→0.88, sobrevive pero preferir maker (EXPERIMENT_LOG) · **spot-only → live long-only permanente** · F6 usa el sandbox stage de Bitso, no Binance testnet. Key de Bitso SIN retiro (§8.3).
- **Dashboard PRIVADO por default** (IAM en Cloud Run, sin `allUsers`): la historia de usuario del reclutador se sirve con el flip `dashboard_public=true` durante demos, o compartiendo la URL tras un flip temporal. Región cloud: **us-central1** (tier-1). Cadencia Cloud Scheduler: diaria 08:10 MX (reemplaza al cron WSL al desplegar).

**2026-07-02 (v0.3 — re-encuadre por evidencia):**
- **Identidad = overlay defensivo + laboratorio de research.** La señal de producción es la regla momentum multi-escala (única validada en holdout); el research continúa como track paralelo con protocolo formal (§8.9). La narrativa pública es la honesta: sin alpha absoluto, valor defensivo demostrado.
- **Grafo:** `quant_core` migra a la regla momentum (Fase 1); el slot **shadow** lo ocupa el mejor **modelo de regresión sobre variables continuas** (no necesariamente LightGBM) — el research pivota de clasificación binaria a regresión.
- **Kelly = TBD con proceso:** interim 0.10; el valor definitivo sale de `/brain:calibrate-risk` sobre la señal nueva (Fase 6).
- **Whitelist:** **XRP/USDT reemplaza a MATIC/USDT** (delistado). `HERMES_MAX_POSITIONS=6`.
- **Noticias §8.7: se mantiene P0** (Fase 4).
- **Protocolo de research v2:** holdout histórico absorbido; juez final = track record vivo; promoción vía shadow ≥ 90 días (§8.9).
- **Orden del runbook:** señal → neteo → dashboard → noticias → GCP → testnet (§9).

**2026-06-28:**
- **Cartera, no apuesta única:** allocator `conf × inverse-vol`, rebalanceo diario por delta vs libro; short ultra-conservador (`P ≤ 0.25`, cap 10%, futuros-only, OFF en live). Budget $1 paper / $50 cloud. → Capa de decisión implementada en PR #10.

**2026-06-26 (v0.2):**
- **Exchange: Binance** (testnet estable, acepta MX).
- **LangGraph nativo** (no TradingAgents; se adopta su estructura de debate bull/bear).
- **El número lo decide el cuant, no el LLM** (§8.7.2) — los agentes verifican/explican, jamás originan.
- Tope de gasto LLM post-POC: $150/mes.

---

## 14. Apéndice — Trabajo relacionado
- **TradingAgents** (Tauric Research) — inspiración de la estructura de debate multiagente.
- **Advances in Financial Machine Learning** (López de Prado) — purged/embargoed walk-forward, PSR, DSR, triple-barrier.
- **TradingGoose**, **Vibe-Trading** (HKUDS) — multiagente para portafolios.
- **ccxt** — librería unificada de exchanges cripto.
