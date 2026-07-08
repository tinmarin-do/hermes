# Diseño pre-registrado — H10: el programa del "doctor en procesos estocásticos"

> **Fecha de pre-registro:** 2026-07-07 · **Estado:** FIJADO (GO de Erika 2026-07-07,
> noche) — commiteado ANTES de correr cualquier sub-experimento (orden auditable en git).
> **Origen:** pregunta de Erika ("¿qué variables elegiría un doctor en finanzas experto
> en procesos estocásticos?") tras la falsificación de H9. **Principio rector:** no
> "mejores variables para la misma pregunta", sino **preguntas más fáciles** (vol,
> spreads estacionarios) e **información más fresca** (carry, flujo, noticias).
> **Regla de oro:** criterios fijados aquí, nada se ajusta tras ver resultados.

## 0. Estructura de la familia y contabilidad DSR

| Sub-H | Pregunta del doctor | Trials nuevos | Naturaleza |
|---|---|---|---|
| **H10.1** | ¿La información NUEVA (funding, flujo comprador) predice dirección donde el precio solo no pudo? | 4 | experimento direccional |
| **H10.2** | ¿Los spreads ESTACIONARIOS entre símbolos revierten de forma explotable (OU/cointegración)? | 2 | experimento relativo |
| **H10.3** | ¿Predecir VOLATILIDAD (lo único muy predecible) mejora al campeón vía vol-targeting? | 1 | overlay de riesgo |
| **H10.4** | ¿Las NOTICIAS aportan señal? — forward-only en shadow (decisión 2026-07-07) | 0 (forward) | protocolo de scoring |
| **H10.5** | ¿Dirección del precio con features de precio? | 0 | **CERRADA** (dónde-no-ir #16, H9) |

**n_trials del DSR: 30** (acumulado documentado: 20 tras H9 + 7 nuevos de H10.1-10.3,
redondeado hacia ARRIBA — vara más dura). Cada sub-H se evalúa contra sus criterios
propios; ninguna "rescata" a otra. Ejecución en orden 10.3 → 10.1 → 10.2 (de la más
barata/segura a la más exótica); 10.4 corre en paralelo desde que exista el logging.

**Común a todo:** ventana de iteración `2021-01-01 → 2025-06-28` (holdout intocado);
universo = whitelist 6; fees 36 bps/lado primario, 10 bps secundario; seed 42; $0
(APIs públicas gratis + cómputo local; los $30 GCP solo con /cost:gate si local no
alcanza); vara = campeón H6 re-corrido bajo tubería idéntica (números de
`research/h9/`); walk-forward purgado (purga 500h, embargo = horizonte); pooled
**con dummy de símbolo** (lección del hallazgo 0 de la auditoría H9); scaler per-fold.
Código de research en `research/h10/` (reproducible, committeado con resultados).

**Pre-requisito de conformidad:** antes de correr H10, cerrar la auditoría H9
(fix dummy de símbolo + re-run de conformidad de los 6 trials — estación 4). Si el
re-run cambiara el veredicto de H9, H10 se re-plantea antes de correr.
✅ **CUMPLIDO 2026-07-07:** veredicto H9 ratificado con dummies (commit `058146f`).

> **Enmienda pre-run 3 (2026-07-07, decisión de Erika, ANTES de correr H10.1/H10.2):**
> **promoción a DOS niveles.** (a) **Vara LIVE** (sin cambios): los 4 criterios
> completos custodian el capital real. (b) **Shadow-bar** (nueva): un trial que no
> alcanza la vara live pero cumple **Sharpe > vara del brazo + PSR(0) > 0.90 + IC > 0**
> (fee 36bps) gana slot en shadow, donde el juez es el track record forward (§8.9 v2).
> Aplica SOLO a trials aún no corridos (H10.1, H10.2) — NO retroactiva (H9 y H10.3
> conservan sus veredictos).
>
> **Decisión de PRODUCTO (Erika, 2026-07-07, registrada como gobernanza — no research):**
> el overlay de vol-targeting de H10.3 va a **shadow como capa de RIESGO** (variante del
> campeón, SIN claim de alpha — su falsificación como alpha queda intacta, lección #20).
> Juez forward: si en N meses la curva shadow confirma el perfil (menos drawdown,
> Sharpe ≥ campeón), se considera para live como guardrail con su propio proceso.
> Implementación: junto con el logging H10.4 (PR propio con tests — toca src/brain).

---

## H10.1 — Carry y flujo: funding rates + taker imbalance

**Hipótesis económica:** el funding rate de perpetuos es un precio OBSERVABLE del
posicionamiento apalancado (crowding): funding extremo-positivo = longs pagando por
apalancarse = fragilidad bajista, y viceversa. El taker imbalance (volumen agresor
comprador vs vendedor) es presión de demanda real. Ambas son información que el
precio spot solo NO contiene — el eje que H9 no probó.

**Datos nuevos (pilot-first: NO se toca el medallón de producción):**
- Funding rates históricos de perps USDT-margined (Binance público vía ccxt
  `fetchFundingRateHistory`, cada 8h, 2021→2025) → tabla research `h10_funding`.
- Taker buy volume horario (campo extendido de klines Binance, API pública REST)
  → tabla research `h10_taker`. Si un símbolo no tiene perp/historia en parte de la
  ventana, sus filas se descartan (se reporta el % descartado).
- La ingesta al medallón (src/) SOLO se construye si H10.1 pasa (patrón news lab).

**Features (fijas a priori; + las 4-6 mom del campeón como base — el criterio es
superar a la vara, no a H9):**

| Feature | Definición | Hipótesis |
|---|---|---|
| `fund_now` | último funding 8h anualizado | carry/crowding instantáneo |
| `fund_z90` | z-score del funding vs 90d | extremos = fragilidad |
| `fund_d7` | Δ funding 7d | giro del posicionamiento |
| `taker_imb` | media 24h de (taker_buy/total − 0.5) | presión neta de demanda |
| `taker_imb_z90` | z-score 90d del anterior | anomalía de flujo |

**Setup:** brazos A (24h diario con-estado + banda, PPY 365) y B (7d semanal), como H9.
**Trials (4):** {Ridge α=1.0, LGBM chico (hiperparámetros idénticos a H9)} × {A, B}.
Target, dead-zone τ=0.1σ, mapping conf: idénticos a H9.

**Criterios de promoción (los 4, por trial, en su brazo, fee 36bps — idénticos a H9):**
IC>0 p<0.05 · Sharpe > vara H6 mismo brazo · PSR(0)>0.95 ∧ DSR(n=30)>0.90 · robustez
anual (no perder vs H6 en >2 de 5 años). **Muerte:** dónde-no-ir; el funding puede
renacer solo como INSUMO de riesgo (crowding para el comité), no como señal.

---

## H10.2 — Spreads estacionarios: reversión OU / cointegración

**Hipótesis económica:** aunque cada precio sea impredecible, una COMBINACIÓN
cointegrada (p.ej. log ETH − β·log BTC) puede ser estacionaria y revertir a su media
(proceso Ornstein-Uhlenbeck) — se predice el objeto estacionario, no el precio.

**Setup (todo a priori):** 15 pares posibles de los 6 símbolos. Por fold walk-forward:
Engle-Granger sobre log-precios en ventana rolling de 90d; el par es "tradeable" ese
período si p<0.05 **y** half-life OU ∈ [2, 30] días. Señal: z = spread/σ_rolling;
entrada |z|>2 contra el spread, salida |z|<0.5 o timeout 2×half-life. Rebalanceo
diario de la cartera de spreads activos, equal-weight.

**Trials (2):**
- **T-neutral:** long leg barata / short leg cara (budget/2 por pierna). ⚠️ Fees
  DOBLES (2 piernas × 2 lados = 4×36bps por round-trip ≈ 1.44%) y **NO desplegable
  live** (Bitso long-only, regla #8) — corre como conocimiento/shadow-only.
- **T-tilt (desplegable):** versión long-only — tilt de ±10% de peso dentro del libro
  del campeón (sobrepesar la pierna barata, subponderar la cara), sin shorts.

**Criterios:** T-neutral: PSR(0)>0.95 ∧ DSR(n=30)>0.90 ∧ Sharpe>0.5 neto de fees
dobles (spread puro no compite contra la vara direccional — compite contra CERO con
costo real). T-tilt: mejora Sharpe Y maxDD del libro del campeón (mismo brazo/fees)
∧ PSR>0.95 ∧ DSR>0.90. **Muerte:** dónde-no-ir #20 candidato ("stat-arb no vive en
majors correlacionados de este universo/era").

---

## H10.3 — Vol-targeting: predecir lo predecible y usarlo de freno/acelerador

**Hipótesis económica:** la vol es persistente y pronosticable; escalar la exposición
del campeón a vol-objetivo constante (bajar exposición cuando la vol pronosticada
sube) mejora Sharpe y drawdown SIN predecir dirección — el free lunch documentado
del vol-targeting.

**Setup (a priori):** brazo A (diario). Pronóstico: EWMA RiskMetrics λ=0.94 sobre los
retornos diarios del libro del campeón. Exposición: `min(1, σ_target/σ_forecast)`
con **σ_target = 25% anual (fijo)**. El multiplicador escala los targets del
allocator (equivale a `global_mult` determinista). Fees sobre el turnover extra real.
**Diagnóstico complementario (sin DSR):** regresión Mincer-Zarnowitz de
`garch_vol`/EWMA vs vol realizada — mide la CALIDAD del pronóstico de vol en sí.

**Trial (1).** **Criterios:** Sharpe > campeón brazo A mismo fee ∧ maxDD mejor
∧ PSR(0)>0.95 ∧ DSR(n=30)>0.90 ∧ robustez anual (no perder vs campeón >2 de 5 años).
**Si pasa:** va al slot shadow como variante del campeón (no toca producción sin su
propio track record — §8.9 v2). **Muerte:** el vol-targeting no aplica a este perfil
de estrategia (posible: el campeón ya es implícitamente anti-vol vía inverse-vol).

---

## H10.4 — Noticias forward-only (protocolo de scoring, sin backtest)

Sin archivo histórico no hay backtest honesto (decisión 2026-07-07).
**Ratificado por Erika tras el cierre del arco (2026-07-07, noche): las noticias
PASADAS quedan descartadas DEFINITIVAMENTE como inferencia** — ni backtest ni features
históricas, ni ahora ni después. El eje de noticias vive EXCLUSIVAMENTE hacia adelante
bajo este protocolo. Pre-registro del
protocolo forward: desde el despliegue del logging, cada corrida diaria persiste el
vector de features de noticias por símbolo (activación de clusters F4.0, novelty
[% titulares sin cluster], sentimiento trust-weighted). Se puntúan contra retornos
realizados a 24h y 7d. **Gates:** ninguna claim antes de **n ≥ 90 días** de señales;
al llegar, IC>0 p<0.05 en al menos un horizonte para pre-registrar un experimento
direccional formal (que tendrá su propio DSR). Hasta entonces: solo acumula.

## H10.5 — Dirección con features de precio: CERRADA

Sin trials. Referencia: H9 (dónde-no-ir #16-17). Se lista para que la familia H10
cubra las 5 respuestas del doctor y quede constancia de que esta puerta se cerró
con evidencia, no por olvido.

---

## Orden de ejecución, entregables y costo

1. **Paso 0 (conformidad H9):** fix dummy símbolo + re-run 6 trials H9 (estación 4 de
   la auditoría en curso). Veredicto H9 se ratifica o se corrige — ANTES de H10.
2. **H10.3** (más barata, datos ya locales) → 3. **H10.1** (pulls públicos ~30-60 min)
   → 4. **H10.2** → 5. logging de **H10.4** (diseño de implementación aparte — toca
   src/brain, va con su propio PR y tests).
3. Cada sub-H: resultados + veredicto → `EXPERIMENT_LOG.md` (una entrada por sub-H,
   n_trials acumulando) → PR con scripts en `research/h10/`.
4. **Costo:** $0 LLM / $0 GCP (APIs públicas + local). Si algo requiriera cloud:
   /cost:gate antes, envelope $30.
