# Diseño — Allocator de portafolio + short conservador (POC $1 → $50)

> **Estado:** Capa de decisión **IMPLEMENTADA** en `feature/portfolio-allocator` (2026-06-28).
> Diferido a próximos incrementos: **neteo del PaperAdapter** (rebalanceo real con reciclaje
> de caja) y **vista de cartera en el dashboard**. — 2026-06-28
> **Filosofía:** data + ciencia primero. La columna cuantitativa decide el número;
> los agentes LLM solo confirman, vetan o recortan (§8.7.2 del PRD).

---

## 1. Motivación — de "francotirador" a "asignador de cartera"

El motor actual es **winner-takes-all**: `quant_core_node` (`src/brain/agents/quant.py`)
recorre los símbolos permitidos, se queda con el de **mayor confianza** y descarta el
resto; el grafo refina esa única apuesta y `runner.py` ejecuta **una sola orden**. El
sizing es un monto absoluto vía Kelly (`CAPITAL × conf × kelly_fraction × vol_scalar`),
no un peso de cartera.

Queremos un **portafolio**: repartir un budget fijo entre los 6 símbolos permitidos,
**rebalanceado a diario**, preservando intacta la jerarquía de decisión de 15 nodos.

## 2. Modelo de budget

| Entorno | Cuándo | Capital | Naturaleza |
|---------|--------|---------|------------|
| **local / paper** | ahora | **$1 imaginario** | Sandbox. Día 0 arranca con $1 en cash. Fraccional, sin min-notional. |
| **cloud / real** | al despegar | **$50 USD reales** | Capital de **trading**, bolsillo **distinto** del cap operativo POC ($50 = GCP $10 + LLM $40). Entra **testnet primero** y no opera live sin guardrails (regla #4). |

> Nota PaperAdapter: no hay check de min-notional (un $1 fraccionado funciona); `quantity`
> se redondea a 6 decimales; la fee (`size×0.001`) redondea a $0 a escala $1; hay check de
> `Insufficient balance` → sembrar el balance paper en $1.

## 3. Mecanismo — rebalanceo por pesos objetivo

Un único mecanismo cubre el día 0 y los días siguientes:

```
cada día:
  1. quant_core scorea los 6 símbolos          → dirección + confianza por símbolo
  2. allocator normaliza a pesos objetivo w_i   → sobre el budget desplegable
  3. ejecución = delta entre w_objetivo y el libro ACTUAL:
        objetivo > actual    → BUY  (agregar)
        objetivo < actual    → SELL (recortar)
        objetivo ≈ actual     → HOLD
        objetivo = 0 y tenés → SELL (salida total)
```

- **Día 0** es el caso especial: cartera = 100% cash → todo son BUY. Mismo código.
- **buy/sell/hold caen del delta** entre objetivo y tenencia; no hay lógica aparte.
- El **desempeño** entra por dos vías: (a) las señales frescas ya incorporan el precio
  nuevo, y (b) `risk`/`PM` pueden forzar recorte/salida si una posición está muy en rojo
  (tipo stop-loss).

## 4. Método de pesos

```
w_i ∝ confidence_i / garch_vol_i        (conf × inverse-vol; reutiliza GARCH de Gold)
w_i = w_i / Σ w_j                         (normalizar entre los símbolos con señal activa)
size_usd_i = budget × global_mult × w_i   (resto → cash)
```

`global_mult ∈ [0,1]` es el **multiplicador global de convicción** que producen
debate/trader (reutiliza el `debate_multiplier` existente): escala cuánto del budget se
despliega. Penalizar la volatilidad (inverse-vol) mantiene la coherencia con el Kelly actual.

## 5. Direccionalidad y política de short (ULTRA-CONSERVADORA)

**Long** se origina con `P ≥ 0.65` (sin cambio). **Short** habilitado pero
asimétricamente penalizado — *data-first, el comité de riesgo es el portero estricto*.

### 5.1 Origen — `quant_core` (umbrales asimétricos)
Un short **solo** nace si se cumplen **las tres** condiciones:
- `P ≤ 0.25`  (mucho más exigente que el 0.35 simétrico actual)
- confianza `|P−0.5|×2 ≥ 0.50`
- **confirmación de régimen bajista** (Hurst en tendencia + drift negativo — no ruido de mean-reversion)

Si no llega a esa vara → **HOLD**, nunca short. *El short nace solo con evidencia fuerte.*

### 5.2 Portero — comité de riesgo (`risk`, política short-específica)
- **Cap de exposición corta ≤ 10% del budget** (los longs hasta 100%).
- **VaR más ajustado** para shorts (pérdida no acotada) + **stop-loss obligatorio** definido.
- **Sin shorts correlacionados** (no cortar majors que se mueven juntos → concentración).
- **Veto duro** si la confianza de la data < barra alta.

### 5.3 Freno — debate / trader / PM (sin cambios estructurales)
- El **bear debe citar la evidencia cuant** (P, confianza, VaR, régimen) para sostener un short.
- El `debate_multiplier` **dampea extra** los shorts (factor de cautela adicional).
- Los LLM **jamás originan** un short — solo lo frenan.

### 5.4 Venue (realidad de ejecución)
- Short real = **futuros** (`binanceusdm`): margen, liquidación, funding. **Spot no puede shortear.**
- **Paper:** short **simulado** (el PaperAdapter solo invierte el signo del P&L) — sirve para calibrar la política sin riesgo.
- **Live:** short **OFF por default**; se habilita **opt-in** recién tras validar la política
  con `/brain:calibrate-risk`. Live arranca **long-only** hasta que la data demuestre que el portero funciona.

## 6. Cadencia diaria y gobernanza de costo

Una corrida **programada no puede pasar por `/cost:gate` interactivo** → choca con la
**regla #6**. Solución: **pre-autorizar una línea de budget diario** en el ledger
(~$0.0075/día ≈ **$0.23/mes** contra el cap de $40). El cron consume contra esa línea y
**se frena** si la supera.

- **Tooling:** cron local / `/loop` ahora; **Cloud Scheduler** / `/schedule` en cloud.

## 7. Cambios de implementación (la jerarquía de 15 nodos NO cambia)

| # | Archivo | Cambio | Estado |
|---|---------|--------|--------|
| 1 | `src/brain/state.py` | + `quant_signals`, `current_positions`, `allocations`. | ✅ hecho |
| 2 | `src/brain/runner.py` | inyectar posiciones al estado **ANTES** del grafo; sembrar budget en el PaperAdapter; ejecutar el **vector** de legs. | ✅ hecho |
| 3 | `src/brain/agents/quant.py` | emitir los **6** quant signals + umbrales **asimétricos** + gate de short por régimen. | ✅ hecho |
| 4 | `src/brain/agents/allocator.py` | **NODO NUEVO** — pesos `conf×inv-vol`, cap short 10%, delta vs libro. | ✅ hecho |
| 5 | `src/brain/graph.py` | cablear `allocator` después del PM. | ✅ hecho |
| 6 | `src/brain/agents/{risk,pm}.py` | El cap/veto de short se enforce **determinísticamente en el allocator** (más estricto y data-first que un LLM); risk/pm quedan como freno global vía `risk_approved`/`debate_verdict`. | ✅ (vía allocator) |
| 7 | `tests/unit/test_allocator.py` + `tests/e2e/test_pipeline.py` | tests del allocator (9) + e2e adaptado al contrato de cartera. | ✅ hecho |
| 8 | `src/execution/adapter.py` | **neteo/reciclaje de caja** para rebalanceo diario real (hoy append-only). | ⏳ diferido |
| 9 | `src/dashboard/build.py` | vista de cartera (pesos, P&L por símbolo, cash). | ⏳ diferido |

## 8. Costo y métricas

- **Costo LLM plano** (~$0.0075/corrida): el grafo corre **una pasada** sobre la cartera,
  no una por símbolo. El allocator es determinista (sin LLM).
- **Turnover y fees** a vigilar a escala $50 (en paper $1 la fee redondea a $0). El
  rebalanceo diario genera rotación; un dampener "no churn" puede sumarse si hace falta.

## 9. Decisiones tomadas (2026-06-28)

- Método de pesos: **conf × inverse-vol**.
- Día 0: **long-only, hasta 6**.
- Día 1+: **acción libre buy/sell/hold** por delta vs libro (rebalanceo con estado).
- Short: `P ≤ 0.25`, conf ≥ 0.50, confirmación de régimen; **cap 10%**; futuros-only en real; OFF por default en live.
- Budget: **$1 paper local ahora**, **$50 reales en cloud** al despegar.

## 10. Pendiente / a calibrar

- Umbrales (`P≤0.25`, conf≥0.50, cap 10%) son punto de partida conservador → calibrar con `/brain:calibrate-risk`.
- Manejo de MATIC/USDT: sin datos recientes en Binance (delistado/renombrado a POL) — decidir si se reemplaza en la whitelist.
- Stop-loss exacto y dampener de turnover.
