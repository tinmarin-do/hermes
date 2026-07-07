# Diagnóstico E2E — "¿Por qué no veo ganancias?" (2026-07-07)

**Auditora:** Claude Fable 5 (sesión remota) · **Solicitado por:** Erika · **Alcance:** camino
de decisión buy/sell/hold de punta a punta + atribución del P&L live (2026-07-03 → 07-07).
**Modo:** solo lectura — cero cambios de código, cero LLM, cero ops GCP ($0.00 esta sesión).

> **Nota de datos.** Esta sesión corrió en un contenedor remoto sin el DuckDB local ni
> credenciales GCP, y Binance responde 451 (geo-bloqueo) desde acá. Los precios públicos
> vienen de **Kraken** vía ccxt (cierres diarios UTC; para estos majors el basis vs Binance
> es despreciable frente a los movimientos medidos). Los montos de la cartera vienen del
> **ledger auditado** (`docs/cost_ledger_llm.md`) y de `REVIEW_FINAL_2026-07-06.md`. El
> Apéndice B da la receta de 2 minutos para computar el número exacto desde el DuckDB live.

---

## §0 Veredicto ejecutivo

**No hay ganancias porque (en orden de importancia):**

1. **El mercado cayó justo después del despliegue.** El capital se desplegó el 07-04
   (~$430 de $565.97) y la canasta entera bajó desde entonces. Hermes perdió **≈ −$7 a −$9
   (−1.2% a −1.6%)** — y aun así **perdió MENOS que haber estado 100% invertido** (−1.64%):
   el colchón de cash (~24%) amortiguó. La defensa documentada funcionó; simplemente no
   hubo mercado que ganar en estos 4 días.
2. **El dashboard muestra P&L $0 por diseño** (hallazgo G de la revisión final:
   `BitsoAdapter.get_positions` pone `entry_price = precio actual` → `unrealized_pnl=0`,
   `src/execution/bitso.py:351-381`). Erika no ve ni las pérdidas ni las ganancias — es un
   **bug de percepción, no de trading**, y es el fix más barato de esta lista.
3. **4 días es ruido puro.** La vol diaria de la canasta es ~2.4%; a 4 días eso es
   **±$26 (1σ) sobre $551**. Ninguna estrategia — la actual o cualquier futura — puede
   demostrar nada en esta ventana (§1, caja estadística).
4. **Lo estructural: el campeón desplegado está documentado SIN alpha absoluto.** La regla
   momentum multi-escala se validó en holdout como overlay **defensivo** (+2.2% en un crash
   de −40%, PSR(0) 0.585 — `EXPERIMENT_LOG.md`, H6/holdout). No hay bug que arreglar ni
   tornillo que apretar: **ganar dinero absoluto requiere un pivote de research**, y el
   camino con evidencia a favor es el challenger de regresión en shadow — la propuesta de
   Erika, con las correcciones metodológicas de §4.1.

La auditoría E2E (§2) **no encontró ningún defecto que se esté comiendo ganancias**. El
sistema hizo exactamente lo que su documentación dice: desplegó cuando hubo señal y
convicción, congeló cuando no, y ejecutó con fees y caps correctos.

---

## §1 Qué pasó realmente en los 4 días live

### Cronología (del ledger auditado — cada run_id es verificable)

| Fecha (UTC) | Corrida | Qué pasó |
|---|---|---|
| 07-03 | 29cb1a50 | 1ª corrida live: wallet $566.07; BUY SOL $430 **rebotó** (bolsillo USDT insuficiente → hallazgo pockets). $0 movido. |
| 07-03 | c385db10, c08a55c2 | Fix de pockets; luego carrera 0379; luego verdict HOLD 80% → freeze. $0 movido. |
| 07-04 | 4da7d525 | 1ª daily 100% autónoma: BUY SOL $366.99 REJECTED (0379, reserva >10s). $0 movido. |
| 07-04 | **2522b64a** | 🏆 **Primer rebalanceo completo live** — BUY 80%, 4/4 FILLED: ETH $98.63 + LINK $92.28 + SOL $142.71 + XRP $96.90 ≈ **$430 desplegados**, cash $113.78. |
| 07-04 | e5681b40 | Watchdog: breach intradía real **−3.8%** (ya rebotado) → comité de emergencia → HOLD/freeze. |
| 07-05 | a0670332 | Daily día 2: HOLD convergido (targets ≈ libro), 0 órdenes, 0 fees. Wallet $556.06. |
| 07-06 | — | REVIEW_FINAL reporta cartera ~$551 (lectura intradía). |
| 07-07 | 6d3213c5 | Validación revisión final: HOLD 80% convergido, banda 5% activa, 0 órdenes. |

Es decir: **la cartera estuvo en cash hasta el 07-04**, se desplegó una sola vez, y desde
entonces el allocator convergió (deltas < banda 5%) — comportamiento anti-churn por diseño.

### Atribución de P&L (pesos reales del rebalanceo × cierres públicos)

Entrada proxy = cierre UTC del 07-04 (el fill fue ~14:10Z; el Apéndice B da el exacto):

| Símbolo | Cierre 07-04 | Cierre 07-07 | Retorno | USD desplegado | P&L |
|---|---|---|---|---|---|
| ETH | 1780.72 | 1777.50 | −0.18% | $98.63 | −$0.18 |
| LINK | 8.0095 | 7.8277 | −2.27% | $92.28 | −$2.09 |
| SOL | 81.80 | 81.00 | −0.98% | $142.71 | −$1.40 |
| XRP | 1.1570 | 1.1170 | −3.46% | $96.90 | −$3.35 |
| **Total precio** | | | | **$430.52** | **−$7.02** |

- Fees del despliegue: −$1.29 (maker 0.30%) a −$1.55 (taker 0.36%).
- **P&L estimado 07-04 → cierre 07-07: ≈ −$8.3 a −$8.6 (−1.5% del wallet).**
- Consistencia con lo documentado: wallet $565.97 (07-04) → $556.06 (07-05, ledger) →
  ~$551 (07-06 intradía, REVIEW_FINAL) → ≈ $557.5 esperado al cierre 07-07 (el mercado
  rebotó parcialmente el 07-07). Las diferencias restantes son intradía + dust BTC/SOL.

### Benchmarks del mismo periodo (07-04 → 07-07)

| Estrategia | Retorno | En USD sobre $565.97 |
|---|---|---|
| **Hermes real** (~76% desplegado conf×inv-vol) | **≈ −1.5%** | ≈ −$8.5 |
| 100% invertido equal-weight 6 | −1.64% | −$9.27 |
| 100% cash | 0.00% | $0.00 |
| Mejor símbolo posible (BTC, no comprado) | +1.62%* | — |

*BTC quedó fuera del rebalanceo del 07-04 (dust previo + pesos conf×inv-vol del día); desde
el cierre del 07-03 BTC +1.62%, pero desde el cierre del 07-04 (la entrada real) todos los
símbolos de la whitelist cerraron el 07-07 planos o abajo.

**Lectura honesta:** en la única ventana live que existe, Hermes hizo *mejor que su
benchmark de mercado* y *peor que cash*. Eso es exactamente el perfil documentado del
overlay defensivo. No hay anomalía que explicar.

### Caja de honestidad estadística — cuánto tarda "ver ganancias"

Con vol diaria de canasta ~2.36% (90d), el ruido a 4 días es **±4.7% (±$26)**: cualquier
P&L de esta semana es indistinguible de cero. Para distinguir una estrategia de Sharpe S
de una moneda al aire (t≈1.645, 95% una cola) se necesita **t ≈ (1.645/S)² años**:

| Sharpe real de la estrategia | Años de track record necesarios |
|---|---|
| 0.5 | ~10.8 |
| 0.9 | ~3.3 |
| 1.5 | ~1.2 |
| 2.0 | ~0.7 |

Esto aplica a CUALQUIER estrategia — incluida la regresión propuesta. Por eso el juez del
protocolo §8.9 es el track record shadow acumulado, no la impresión de una semana.

---

## §2 Auditoría E2E del camino de decisión

Camino trazado completo: gold → `src/brain/quant_rule.py` (campeón) → comité LLM
(`agents/quant.py` gates de short → debate → `risk.py` con VaR duro → `pm.py`) →
`agents/allocator.py` (pesos, deltas, caps) → `runner.py` (budget wallet, SELLs primero) →
`src/execution/bitso.py` (maker-first, caps de balance, re-query async).

**Resultado: cero bugs que resten ganancias.** Observaciones relevantes a earnings, en
orden de materialidad:

1. **Sub-despliegue estructural: `global_mult = debate_confidence`**
   (`allocator.py:169`). Con BUY 80% solo se despliega el 80% del budget (menos fee
   reserve 0.5%): ~$113 quedaron en cash el 07-04. En ESTA ventana eso **sumó** (+$2.2 vs
   100% invertido); en un rally sostenido sería un drag permanente de ~20%. Es diseño
   (los agentes frenan proporcional a convicción), pero ojo: la "confianza" del debate
   LLM **no es una probabilidad calibrada** — usarla como multiplicador lineal de capital
   es una convención razonable, no una cantidad validada. Si algún día importa el alpha,
   este multiplicador merece su propia calibración (`/brain:calibrate-risk`).
2. **HOLD por símbolo ≠ "mantener": es "target 0"** (`allocator.py:97-108`). Si las
   escalas de momentum entran en desacuerdo para un símbolo held, su target pasa a $0 y
   se vende entero (si el delta supera la banda 5%). Semánticamente correcto para una
   señal momentum (sin señal → sin posición), pero es la fuente principal de churn
   potencial round-trip a 36bps. La banda 5% + freeze global lo contienen; el panel de
   turnover mensual (revisión final #6) es el juez en ~30 días.
3. **Latente — `garch_vol` faltante concentra la cartera**: el peso es
   `conf / max(garch_vol, 1e-4)` (`allocator.py:79-80`). Si a UN símbolo actionable le
   faltara `garch_vol` (→ 0.0 → floor 1e-4) mientras los demás tienen ~0.01, ese símbolo
   recibiría ~100× el peso y absorbería casi todo el budget. Hoy no ocurre
   (validate-silver/gold exigen GARCH), pero el allocator no se defiende solo. Barato de
   blindar cuando se toque ese archivo (no en esta sesión: read-only).
4. **`size_usd` del Kelly (`_kelly_size`) no participa en la cartera**: el allocator
   re-deriva todo de `confidence/garch_vol`; el sizing Kelly solo viste la tesis líder
   del PM. No es bug (el diseño §8.8 lo dice), pero que nadie espere que Kelly esté
   dimensionando las posiciones reales — el Kelly efectivo de cartera es implícito.
5. **Confianza del campeón es gruesa por construcción**: `|votos|/válidas` con 4 escalas
   da básicamente {0.5, 0.95} (`quant_rule.py:33-48`). Los pesos relativos entre símbolos
   los decide sobre todo el inverse-vol. Consistente con H6 ("sin magnitudes que tunear");
   solo conviene saberlo al leer allocations.
6. **Cosméticos**: (a) el fee registrado aplica UNA tasa (maker o taker) a todo el fill
   aunque haya sido mixto limit+market (`bitso.py:218-224`) — impreciso en centavos, solo
   contable; (b) hallazgo G ya descrito (P&L $0 en display); (c) `_past_returns` no
   valida frescura del bronze — si el bronze quedara días viejo, el momentum se calcularía
   silenciosamente sobre datos rancios (hoy lo cubre la cadencia de ingesta + validates).

Verificado también (limpio): fix tz H8 presente (`quant_rule.py:73-75`); as-of por
`bisect_right` sin look-ahead; gates de short (conf ≥ 0.50 + Hurst ≥ 0.50 + drift 24h < 0);
VaR duro anula al LLM (revisión final #2); SELLs antes que BUYs (`runner.py:181-182`);
cap por bolsillo con proceeds de SELLs del mismo bolsillo; BUY capeado a caja libre ×0.995;
re-query del fill asíncrono; freeze conserva el libro (ya no liquida). Nada de lo ya
reportado en REVIEW_FINAL §1-2 se re-reporta aquí como nuevo.

---

## §3 Veredicto sobre cada causa sospechada

| Hipótesis de Erika | Veredicto | Evidencia |
|---|---|---|
| **Selección de modelo** | No es la causa de estos 4 días (fue el mercado). PERO contra el juez nuevo — ganancias absolutas — el campeón es la herramienta equivocada *por su propia documentación*: defensivo, sin alpha (holdout: +2.2% con PSR 0.585). | `EXPERIMENT_LOG.md` H6 + holdout; ML direccional falsificado 3× (LightGBM PSR 0.504; logística DSR 0.223; cross-sectional DSR 0.29-0.31). |
| **Entrenamiento del modelo** | N/A — el campeón no se entrena (regla fija a priori). El LightGBM falsificado murió por label/edge, no por higiene: el walk-forward purgado era correcto y precisamente por eso lo cazó. | `EXPERIMENT_LOG.md` Exp. 0 y protocolo §8.9. |
| **Feature engineering** | **El eje MENOS explorado — y el más prometedor.** El campeón usa solo momentum de precio; Hurst/GARCH/spread de Silver se usan apenas como gates/sizing, no como alpha; las noticias JAMÁS se usaron como input predictivo (solo verificación red-team). Es exactamente donde apunta el challenger de §4.1. | `quant_rule.py` (solo `mom_*`); `agents/quant.py:84` (garch_vol solo sizing). |
| **Solo 6 símbolos** | Falsificado como fuente de alpha: H8-wide amplió a 28 nombres y el spread apenas se movió (DSR 0.29→0.31). Expandir universo ayuda a diversificación/drawdown, no a ganancias. | `EXPERIMENT_LOG.md` H8-wide. |
| **Manejo cartera-como-base** | **Ya está implementado exactamente como lo describís**: pesos objetivo sobre el budget, órdenes = delta vs libro actual, día 0 todo-cash → BUYs, día N rebalanceo con estado. Solo nits residuales (§2.3-2.5). | `DESIGN_portfolio_allocator.md` §3; `allocator.py:97-119`; `runner.py:63-74`. |
| **"Algún detalle chiquito"** | El único "detalle" con efecto real sobre tu percepción es el **hallazgo G**: el dashboard muestra P&L $0 siempre. Los demás hallazgos de §2 son latentes o cosméticos. | `bitso.py:351-381`; REVIEW_FINAL hallazgo G. |

---

## §4 Caminos hacia ganancias absolutas (ranqueados por evidencia)

### 4.1 Challenger de regresión en shadow — tu propuesta, afinada (RECOMENDADO)

Es el arco F ya diseñado (REVIEW_FINAL §2.F, PRD §5.2) y la única vía con un eje de datos
genuinamente virgen. Las correcciones que la evidencia impone a la formulación original:

- **Predecir RETORNOS, no el nivel del precio.** "Predecir el precio de BTC con precisión"
  es una trampa conocida: una regresión sobre niveles da R²≈0.99 solo porque el precio de
  mañana se parece al de hoy (autocorrelación) — cero valor de trading. El target honesto
  es el retorno forward (o vol futura), donde el R² será minúsculo y REAL.
- **Momentum como feature: sí** — exactamente como propusiste; el campeón actual pasa a
  ser un input más del challenger.
- **Noticias como feature predictivo: el eje nuevo de verdad.** La infra de
  embeddings/clusters de Fase 4.0 ya existe y está validada (anti-injection incluido);
  nunca se usó para predecir. Ortogonal a todo lo falsificado.
- **Protocolo §8.9 v2 intocable:** corre en el slot shadow (`src/brain/shadow.py` ya
  persiste por corrida), el juez es su track record contra el campeón con datos del
  futuro, y el campeón no se toca hasta que pierda.

**Secuencia pilot-first (tu directiva del 07-07):** piloto en muestra chica PRIMERO →
juzgar → recién entonces invertir en el rework de Silver ([[project-silver-rework]] —
evolucionar, no reescribir: el campeón live depende de las columnas actuales). Nota
metodológica: en series de tiempo la "muestra chica" válida es una **ventana temporal
reducida / subset de símbolos con walk-forward purgado** — NO sampleo aleatorio de filas
(leakage instantáneo). Sobre disponible: **$30 USD de GCP** si lo local no alcanza — cada
op cloud pasa por `/cost:gate` (reglas #1/#6). Costo LLM del piloto: ~$0 (la regresión es
sklearn/LightGBM local; el LLM no participa del fit).

**Criterio pre-registrado para promover (anti verdict-shopping):** DSR > 0.90 en
walk-forward de iteración + N meses ganándole al campeón en shadow live. Se fija ANTES
de correr el piloto.

### 4.2 Momentum 12-1 con skip de la última semana

La única bala a priori que queda en el mapa de dónde-no-ir (`EXPERIMENT_LOG.md:294`).
Barata (mismo harness de backtest), un solo trial más para el DSR. Puede correr en
paralelo al piloto 4.1.

### 4.3 "Cosechar beta" — la actualización honesta que los datos exigen

La intuición "long-only cripto en año alcista gana solo por estar" **no describe el
periodo actual**. Con cierres públicos Kraken (ventana disponible 2024-07-17 → 2026-07-07):

| Buy & hold 2 años | Retorno |
|---|---|
| BTC | −0.8% |
| ETH | −47.5% |
| SOL | −47.9% |
| LINK | −43.1% |
| AVAX | −75.4% |
| XRP | +78.5% |
| **Equal-weight 6** | **−22.7%** |

El mercado de esta whitelist DESTRUYÓ valor en dos años (solo XRP salvó); el holdout
2025-06→2026-06 fue un crash de −40%. En este régimen, el overlay defensivo — quedarse
plano donde el mercado se desangra — ES la ganancia relativa, aunque no se sienta como
"ver ganancias". Si el objetivo pasa a retorno absoluto incondicional, que sea con los
ojos abiertos: implica tomar beta de un activo que acaba de demostrar que también baja.
(Ventana distinta a la auditoría de cadencia 2024-01→2026-07 del EXPERIMENT_LOG — Kraken
solo sirve 720 velas diarias; no comparar cifras entre ventanas.)

### 4.4 Expandir universo (arco 24 monedas)

Vale por diversificación/drawdown (H8-wide), no por alpha. Tiene sentido DESPUÉS de que
exista una señal con edge que diversificar — hoy multiplicaría símbolos sin ganancias.

---

## §5 Recomendación y próxima sesión

1. **Fix del hallazgo G** (display de P&L real) — chico, y ataca directamente la
   experiencia "no veo ganancias": reconstruir entries desde `execution_orders` y mostrar
   P&L realizado + no realizado + fees acumulados en el tile En vivo. Sin esto, ni las
   ganancias futuras se verán.
2. **Piloto pilot-first del challenger de regresión (4.1)**: ventana/símbolos reducidos,
   target = retorno forward, features = momentum + Silver actual + noticias (embeddings
   F4.0), walk-forward purgado, criterio pre-registrado. Local primero; ≤$30 GCP gateado
   si hace falta. Si el piloto convence → recién entonces [[project-silver-rework]].
3. **12-1 skip** como trial paralelo barato (4.2).
4. **No tocar el campeón ni la cadencia** hasta la revisión de ~30 días ya agendada
   (~2026-08-05, panel de turnover como juez — REVIEW_FINAL §2.D).

Las opciones de §4 son decisiones de Erika; nada de esto se ejecutó en esta sesión.

---

## Apéndice A — Reproducibilidad (corrido en esta sesión, $0)

Precios: ccxt público contra Kraken (Binance responde 451 desde el contenedor; nunca se
deshabilitó verificación TLS — el CA bundle del proxy se pasa vía `validateServerSsl`
porque ccxt colapsa un path en `verify` a `True`, `ccxt/base/exchange.py:660`).

```python
import ccxt, os
ex = ccxt.kraken({"enableRateLimit": True})
ca = os.environ.get("REQUESTS_CA_BUNDLE")          # solo necesario detrás del agent-proxy
if ca: ex.validateServerSsl = ca
for sym in ["BTC/USDT","ETH/USDT","SOL/USDT","LINK/USDT","AVAX/USDT","XRP/USDT"]:
    ohlcv = ex.fetch_ohlcv(sym, "1d", since=ex.parse8601("2024-07-01T00:00:00Z"), limit=720)
```

Atribución (pesos reales del ledger 2522b64a, cierres UTC):

```python
fills = {"ETH": 98.63, "LINK": 92.28, "SOL": 142.71, "XRP": 96.90}   # 2026-07-04
wallet0 = 565.97
pnl = sum(usd * (px["2026-07-07"][s] / px["2026-07-04"][s] - 1) for s, usd in fills.items())
# -> −$7.02 precio; fees despliegue −$1.29 a −$1.55; total ≈ −$8.5 (−1.5%)
```

Vol/ruido y años-para-significancia: desvío estándar muestral de retornos diarios del
basket EW (90d) = 2.36% → σ₄d = 2.36%×√4 = 4.72%; años = (1.645/S)².

## Apéndice B — El número EXACTO (2 minutos, en tu máquina)

```bash
# 1) bajar el DuckDB live (ajustá el bucket de tu tfstate)
gsutil cp gs://<bucket-hermes>/hermes.duckdb /tmp/hermes_live.duckdb

# 2) fills reales con fees
duckdb /tmp/hermes_live.duckdb "
  SELECT filled_at, symbol, action, quantity, price, cost_usd, fee_usd, status
  FROM execution_orders ORDER BY filled_at;"

# 3) curva de equity oficial (dedupe 1 punto/día ya aplicado por la revisión final)
duckdb /tmp/hermes_live.duckdb "
  SELECT ts, equity FROM equity_curve ORDER BY ts;"
```

P&L exacto = equity_hoy − equity_2026-07-03 (y por símbolo: qty de fills × precio actual
− cost_usd − fees). Debería caer dentro del rango de §1 (≈ −$7 a −$9 al cierre del 07-07).
