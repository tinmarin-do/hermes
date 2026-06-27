# PRD — Proyecto Hermes
### Sistema multiagente de trading con IA, desplegado en la nube

| | |
|---|---|
| **Autora** | Erika |
| **Rol** | Product & Tech Lead (solo) |
| **Versión** | 0.2 — Con revisión actuarial y de arquitectura multiagente |
| **Fecha** | 26 de junio, 2026 |
| **Estado** | Revisado y listo para ejecutar |
| **Codename** | *Hermes* (dios del comercio y los mensajeros; combina con el universo "Odysseus". Renombrable.) |

> **Disclaimer.** Hermes es un proyecto experimental y educativo. No constituye asesoría financiera ni de inversión. Opera únicamente con capital de riesgo que se puede perder por completo. El desempeño pasado no garantiza resultados futuros, y un sistema multiagente con LLMs **no** tiene desempeño rentable garantizado.

---

## 1. Resumen ejecutivo (TL;DR)

Hermes es una "firma de trading" simulada por **múltiples agentes LLM** que colaboran y debaten para decidir operaciones sobre criptoactivos, ejecutándolas de forma automatizada en un exchange. El sistema corre 24/7 en GCP, mantiene un **track record auditable** y se expone mediante un dashboard público desplegado.

El objetivo **no** es "ganarle al mercado", sino ser una **pieza de portafolio que demuestre por sí sola** cuatro competencias a la vez: orquestación de IA agéntica, arquitectura cloud/MLOps, producto full-stack de punta a punta, y dominio fintech/cuantitativo con disciplina de riesgo.

---

## 2. Problema y oportunidad

**Problema de portafolio.** Los proyectos de portafolio típicos demuestran una sola competencia (un notebook de ML, una API CRUD, un dashboard). Para roles senior de IA/datos —incluyendo mercados europeos— hace falta una pieza que demuestre criterio de producto **y** profundidad técnica **y** capacidad de llevar algo agéntico a producción.

**Oportunidad técnica.** El trading es un dominio ideal para sistemas multiagente: es naturalmente colaborativo (analistas, debate alcista/bajista, gestión de riesgo) y produce una señal de calidad objetiva y medible (métricas ajustadas por riesgo). Cripto, además, ofrece datos gratuitos vía `ccxt`, mercado 24/7 y operabilidad desde México sin las barreras de los brokers de EE. UU.

---

## 3. Objetivos, métricas y no-objetivos

### 3.1 Objetivos de producto
- **O1.** Un sistema multiagente funcional de punta a punta: datos → decisión → ejecución → registro.
- **O2.** Desplegado y siempre vivo (URL pública demoable a cualquier hora).
- **O3.** Track record transparente y auditable de las operaciones reales.
- **O4.** Que "hable solo" como evidencia de las 4 competencias (IA agéntica, cloud/MLOps, full-stack, fintech).

### 3.2 Métricas de éxito

| Dimensión | Métrica | Meta MVP |
|---|---|---|
| **Funcionalidad** | Pipeline completo corre sin intervención | ✅ corridas automáticas estables ≥ 7 días |
| **Confiabilidad** | Uptime del dashboard | ≥ 99% en la semana de evaluación |
| **Eficiencia (MLOps)** | Costo promedio por corrida de agentes | < umbral definido (ver §11) y visible en dashboard |
| **Latencia** | Tiempo de una corrida completa | Medido y mostrado; demo lee de caché (instantánea) |
| **Disciplina (fintech)** | Métricas ajustadas por riesgo | **Probabilistic Sharpe Ratio (PSR)**, intervalo de credibilidad bayesiano para Sharpe, **Sortino, max drawdown** calculados y mostrados |
| **Disciplina (fintech)** | Respeto de límites de riesgo | 0 violaciones de los caps/kill switch |
| **Adaptabilidad** | Días en ≥ 2 regímenes de mercado visitados | ≥ 30% del tracking period |
| **Portafolio** | Legibilidad para un no-experto | Un reclutador entiende qué hace en < 60 s |

> **Nota técnica:** Sharpe y Sortino requieren ~100+ observaciones para ser estables. Con una muestra chica (< 60 trades) se reporta además el **Probabilistic Sharpe Ratio (PSR)** — que ajusta por no-normalidad y tamaño muestral — y un **intervalo de credibilidad bayesiano** (ej. `Sharpe = 0.4 [90% CI: -0.8, 1.6]`). Esto demuestra honestidad estadística frente a reclutadores cuantitativos.

### 3.3 Qué **no** es éxito (anti-métricas)
- ❌ Un número de rendimiento aislado ("hizo +X%"). Es ruido/suerte en muestra chica.
- ❌ "Ganarle al mercado". No es el objetivo ni una promesa realista.
- ✅ El éxito es el **proceso riguroso + la transparencia**, incluyendo reportar pérdidas con honestidad.

### 3.4 No-objetivos / Fuera de alcance (MVP)
- No es un producto para terceros ni un servicio de asesoría (eso implicaría regulación — ver §8.5).
- No soporta acciones en el MVP (queda como *roadmap*, ver §12).
- No optimiza estrategias de HFT ni microestructura.
- No incluye onboarding de usuarios, pagos, ni multi-tenant.

---

## 4. Usuarios y audiencia

| Audiencia | Tipo | Qué necesita ver |
|---|---|---|
| Reclutadores / hiring managers (IA, fintech, cloud — incl. Europa) | Primaria | Que funciona, que está desplegado, que es sofisticado pero legible |
| Evaluadores del diploma | Primaria | Rigor técnico y de producto |
| Erika (operadora) | Secundaria | Control, observabilidad, seguridad del capital |

---

## 5. Alcance funcional y prioridades

Notación: **P0** = imprescindible para el MVP · **P1** = mejora fuerte · **P2** = *nice to have* / roadmap.

### 5.1 Capa de datos
- **P0** Ingesta de OHLCV y datos de mercado en tiempo real vía `ccxt`.
- **P0** Adaptador de datos para alimentar a los agentes (TradingAgents nace orientado a equities; **adaptar a cripto es trabajo real**, ver §10/§11).
- **P1** Señales de sentimiento/noticias cripto (fuentes gratuitas).

### 5.2 Capa de decisión (el cerebro multiagente)
- **P0** Clasificador de régimen de mercado como primer paso del pipeline: calcula **Hurst exponent** (trending vs mean-reverting), **volatilidad** vía GARCH(1,1) estimada, y **liquidez** (spread). Los analistas reciben el régimen como contexto y ajustan sus indicadores.
- **P0** Integrar **TradingAgents** (LangGraph): régimen → analistas → debate alcista/bajista → trader → equipo de riesgo → portfolio manager.
- **P0** Configuración de modelos por rol/profundidad (modelo rápido y barato/gratuito para analistas; modelo fuerte para trader/PM).
- **P0** Persistir cada corrida: régimen detectado, transcripción del debate, decisión final y racional.
- **P1** Reflexión/aprendizaje entre corridas (memoria).

### 5.3 Capa de ejecución
- **P0** Adaptador de ejecución con interfaz **agnóstica al exchange/broker** (`testnet` → `live`).
- **P0** **Guardrails de riesgo** (ver §8): tamaño máximo de posición, límite de pérdida diaria, kill switch.
- **P0** Registro de cada orden y posición.

### 5.4 Capa de presentación y observabilidad (el showcase)
- **P0** Dashboard público: curva de equity, posiciones actuales, historial de operaciones, **visor del debate de los agentes**.
- **P0** Panel de métricas ajustadas por riesgo (PSR, Sharpe bayesiano, Sortino, drawdown).
- **P0** Frontend liviano: **FastAPI + Jinja2 + Chart.js + htmx** — sin dependencia de Odysseus, deployable en Cloud Run.
- **P1** Botón "correr análisis ahora" (rate-limited) para demos en vivo.
- **P1** Panel de MLOps: costo por corrida, latencia, uptime.
- **P2** Modo "explicación" para reclutadores no técnicos.

### 5.5 Historias de usuario clave
- *Como reclutador*, abro la URL un domingo a medianoche y veo agentes que ya trabajaron, una posición abierta y la curva de equity — entiendo el proyecto sin que nadie me explique.
- *Como evaluadora del diploma*, puedo inspeccionar la transcripción del debate que llevó a una decisión concreta.
- *Como operadora*, defino límites de riesgo y puedo detener todo con un kill switch.

---

## 6. Arquitectura técnica

```
                         ┌─────────────────────────────┐
   Mercado (cripto) ───▶ │  CAPA DE DATOS               │
   ccxt (100+ exch.)     │  OHLCV + régimen + sentimiento│
                         └──────────────┬──────────────┘
                                        ▼
                         ┌─────────────────────────────┐
                         │  CEREBRO MULTIAGENTE         │
                         │  RegimeClassifier → Analysts │
                         │  (condicionados al régimen)  │
                         │  → Debate → Trader → Risk   │
                         │  (VaR+Kelly+correlación) → PM│
                         │  LLMs hosted (modelo x rol)  │
                         └──────┬──────────────┬────────┘
                                │              ▲
                                ▼              │
                         ┌─────────────────────────────┐
                         │  CAPA DE EJECUCIÓN           │
                         │  Adapter agnóstico            │
                         │  testnet → live + GUARDRAILS │
                         │  Feedback: slippage, fills    │
                         └──────┬──────────────┬────────┘
                                │              ▲
                                ▼              │
        ┌───────────────────────────────────────────────────────┐
        │  ESTADO (Cloud SQL/Postgres)                          │
        │  decisiones · órdenes · posiciones · equity · costos  │
        │  ← feedback loop activo: P&L, drawdown, régimen  →   │
        └───────────────┬───────────────────────────────────────┘
                        ▼
         FastAPI + Jinja2 + Chart.js ──▶ Dashboard público
```

> **Nota — feedback loops:** El cerebro nunca opera con información desactualizada. Slippage real y fills parciales desde la ejecución, más el P&L no realizado y drawdown actual desde el estado, alimentan la **siguiente corrida** de los agentes.

**Estrategia de serving de LLM (clave de MLOps):**
1. **Corridas programadas** (Cloud Scheduler), no por visitante → genera decisiones reales y alimenta el track record. Costo acotado y predecible.
2. **La demo pública lee del historial guardado** → instantánea, siempre poblada, costo por visitante = 0.
3. **Botón "correr ahora"** opcional y *rate-limited* para disparar una corrida en vivo durante una entrevista, sin exponerse a costos infinitos.
4. **Modelos hosted** por calidad y cero riesgo de infra en el sprint. *Local (Ollama) en Odysseus queda soportado pero opcional* — un flex de MLOps documentado, fuera de la ruta crítica.

**Principio de diseño — agnóstico al activo.** Tanto datos como ejecución viven detrás de una interfaz (`MarketDataSource`, `ExecutionAdapter`). Cambiar `ccxt` por Alpaca (acciones) = implementar el adapter, sin tocar el cerebro. Esto **es** parte del showcase de ingeniería.

---

## 7. Stack tecnológico

| Capa | Tecnología |
|---|---|
| Lenguaje | Python |
| Cerebro agéntico | TradingAgents (Apache-2.0) sobre LangGraph |
| LLMs | API hosted (config por rol); Ollama/OpenAI-compatible como opción local |
| Datos / ejecución cripto | `ccxt` |
| Backend | FastAPI |
| Persistencia | Cloud SQL (Postgres) — alternativa: BigQuery para analítica |
| Frontend | Dashboard web: **FastAPI + Jinja2 + Chart.js + htmx** (propio, sin dep. externas) |
| Orquestación | Cloud Run (servicios) + Cloud Scheduler (corridas) |
| Secretos | Secret Manager |
| Empaquetado / CI | Docker + GitHub Actions |

---

## 8. Trading, riesgo y seguridad (la parte fintech)

### 8.1 Fases de operación
1. **Paper / testnet** — valida el pipeline completo end-to-end. *Sin dinero real.*
2. **Live mínimo** — capital de riesgo pequeño (a definir, ver §11) con todos los guardrails activos.

> Validar antes de operar real no diluye el "punch": lo hace **creíble**.

### 8.2 Guardrails de riesgo (P0, no negociables)
- **Tamaño de posición por Kelly fraccional (0.25×):** el sizing no es fijo — depende de la confianza del PM y la volatilidad actual:
  | Confianza del PM | Kelly 0.25× | Capital $500 | Capital $2,000 |
  |---|---|---|---|
  | Alta (≥ 70%) | 2.0% | $10 | $40 |
  | Media (50–70%) | 1.0% | $5 | $20 |
  | Baja (< 50%) | 0.5% | $2.50 | $10 |
- **VaR/CVaR pre-trade:** antes de ejecutar, Risk calcula pérdida en escenario de 2 desviaciones. Si excede el límite, la operación se rechaza.
- **Correlación entre posiciones:** si la correlación estimada con posiciones abiertas supera 0.7 y la exposición total excede el límite, la nueva operación se rechaza.
- **Límite de pérdida diaria** → al alcanzarse, se detiene la operación del día.
- **Kill switch** manual y automático (cierra/pausa todo).
- **Lista blanca de símbolos** y número máximo de posiciones simultáneas.

### 8.3 Seguridad
- **API keys del exchange con permisos solo de trading — NUNCA de retiro/withdrawal.**
- Secretos en **Secret Manager**, jamás en el repo ni en el cliente.
- Principio de menor privilegio en todo servicio de GCP.

### 8.4 Evaluación honesta
- **Backtest** sobre histórico (datos gratis vía `ccxt`) + **track record en vivo**.
- Reportar **Sharpe, Sortino, max drawdown** y P&L — **incluyendo pérdidas**.
- Documentar limitaciones (tamaño de muestra, sesgos del backtest, etc.).

### 8.5 Notas regulatorias y fiscales
- Hermes opera **capital propio** como automatización personal/educativa. Ofrecerlo a terceros lo convertiría en asesor de inversiones (en MX: terreno de la **CNBV**) — **fuera de alcance**.
- Las ganancias/pérdidas en cripto pueden tener **implicaciones fiscales en México**. No es asesoría fiscal; consultar a un profesional.

---

## 9. Plan de ejecución — Sprint de 4 semanas

> Comprimible a 2–3 semanas recortando todo lo que no sea **P0**.

| Semana | Hito | Entregable |
|---|---|---|
| **0** | Exploración | Evaluar TradingAgents con datos cripto dummy. Identificar hooks de adaptación. Decisión: TradingAgents vs LangGraph nativo. Interfaz `MarketDataSource` definida |
| **1** | Cerebro + datos | RegimeClassifier + pipeline multiagente corriendo local sobre cripto (paper) con adaptador `ccxt`; arnés de backtest funcional |
| **2** | Ejecución + estado + riesgo | `ExecutionAdapter` contra **testnet**; persistencia en BD; Kelly sizing + VaR pre-trade; corridas programadas; **guardrails + kill switch** |
| **3** | Producto + deploy | Backend FastAPI + dashboard (Jinja2/Chart.js): equity, posiciones, visor de debate, PSR, métricas de riesgo; **desplegado en GCP** |
| **4** | Live + pulido + caso | Flip a **live mínimo** con caps; panel de MLOps (costo/latencia/uptime); README + case study; buffer |

**Definición de "Hecho" (MVP):** pipeline automático estable ≥ 7 días, desplegado y público, con régimen detectado en cada corrida, guardrails respetados (Kelly + VaR + correlación), métricas de riesgo (PSR, Sharpe bayesiano) visibles y un README/case study que lo explique.

---

## 10. Instrumentación y observabilidad
Registrar y exponer: régimen de mercado detectado · decisiones y transcripciones de debate · órdenes y posiciones · curva de equity · **costo por corrida (tokens + USD)** · latencia de corrida · uptime · violaciones de riesgo (debe ser 0) · **gasto acumulado del mes vs. tope de $150**.

---

## 11. Riesgos y mitigaciones

### 11.1 Tabla de riesgos

| Riesgo | Prob. | Impacto | Mitigación |
|---|---|---|---|
| Adaptar TradingAgents (equities→cripto) cuesta más de lo previsto | **Alta** | Alto | **Semana 0** de exploración (2–3 días) antes de comprometer la arquitectura. Clonar, correr local con datos dummy, identificar hooks. Si > 3 días de adaptación, construir multiagente desde cero con LangGraph directamente |
| Costo de LLM se dispara | Media | Alto | Corridas programadas (no por visitante), modelo de costos detallado (ver §11.2), límite de rondas/símbolos, modelo gratuito para analistas, **tope de gasto mensual: $150** |
| Infra propia caída tumba la demo | Baja | Alto | LLMs **hosted**, no local, en la ruta crítica |
| Pérdidas en vivo | Alta | Bajo (financiero) / Medio (narrativa) | **Capital mínimo**; framing de éxito = proceso, no número; reportar con honestidad |
| Fuga de API key | Baja | Crítico | Keys **solo-trade (sin retiro)** + Secret Manager |
| Scope creep en 4 semanas | Alta | Alto | Disciplina **P0 estricta**; P1/P2 solo si sobra tiempo |

### 11.2 Modelo de costos de LLM

Estimación con modelos de OpenCode Zen (precios por 1M tokens, junio 2026):

| Rol | Modelo sugerido | Costo input | Costo output | Toks/corrida | Costo/corrida |
|---|---|---|---|---|---|
| RegimeClassifier | DeepSeek V4 Flash Free | $0 | $0 | ~5K | $0 |
| Analysts (×3) | DeepSeek V4 Flash Free | $0 | $0 | ~30K c/u | $0 |
| Trader | DeepSeek V4 Flash | $0.14 | $0.28 | ~20K | ~$0.006 |
| Risk | DeepSeek V4 Flash | $0.14 | $0.28 | ~15K | ~$0.004 |
| Portfolio Manager | GPT-5.4 Mini | $0.75 | $4.50 | ~25K | ~$0.12 |
| **Total por corrida (free analysts)** | | | | | **~$0.13** |
| **Total por corrida (modelos fuertes)** | | | | | **~$0.80** |

**4 corridas/día → ~$15.60/mes** (con free models para analistas) o **~$96/mes** (con modelos fuertes para PM/Risk).

> **Tope de gasto mensual en LLMs:** $150. El dashboard muestra $$ gastado / $$ restante del mes. Al alcanzar el tope, las corridas se pausan automáticamente hasta el mes siguiente.

---

## 12. Roadmap / trabajo futuro
- **Portar dashboard a Odysseus UI:** convertir Hermes en agente nativo dentro del workspace Odysseus (post-MVP).
- **Acciones vía Alpaca** (paga el dividendo del diseño agnóstico al activo).
- **Serving local** de modelos en Odysseus (Ollama) como modo de bajo costo.
- Más agentes / estrategias múltiples / memoria de largo plazo / modelos de régimen más sofisticados (cambio de Markov).

---

## 13. Decisiones abiertas (a confirmar)
- **Exchange**: se recomienda **Binance** (testnet estable, acepta MX, máxima liquidez). BTC/USDT primario, ETH/USDT secundario. Confirmar.
- **Semana 0**: evaluar TradingAgents vs LangGraph nativo. Decidir antes del día 3.
- Niveles de modelo exactos por rol y **tope de gasto**: $150/mes confirmado.
- Monto de capital para la fase live mínima: recomendado $500–2,000.

---

## 14. Apéndice — Trabajo relacionado (para citar)
- **TradingAgents** (Tauric Research) — framework multiagente LLM sobre LangGraph; el "cerebro" de Hermes.
- **TradingGoose** — multiagente para análisis y gestión de portafolios.
- **Vibe-Trading** (HKUDS) — workspace agéntico con swarms y datos cripto.
- **ccxt** — librería unificada de exchanges cripto.