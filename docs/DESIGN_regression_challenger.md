# Diseño pre-registrado — Challenger de regresión (Experimento H9)

> **Fecha de pre-registro:** 2026-07-07 · **Estado:** FIJADO antes de correr el piloto
> (este documento se commitea ANTES que cualquier código o resultado del piloto — el
> orden queda auditado en git). **Origen:** propuesta de Erika (diagnóstico
> `DIAGNOSTIC_EARNINGS_20260707.md` §4.1) + diseño acordado 2026-07-04.
> **Regla de oro:** nada de lo fijado aquí se ajusta después de ver resultados
> (anti verdict-shopping, protocolo `EXPERIMENT_LOG.md` §1-5).
>
> **Enmienda pre-run (2026-07-07, decisión de Erika, ANTES de ejecutar nada):** se
> agrega un **segundo horizonte de 24h con evaluación diaria realista** (libro
> persistente + banda anti-churn + fees sobre turnover real). Motivación: medir
> performance a diario y rebalancear a diario sin auto-boicot (horizonte = cadencia).
> Trials: 3→6; n_trials del DSR: 15→18. Enmienda legítima: ningún resultado se había
> observado al momento de fijarla.
>
> **Enmienda pre-run 2 (2026-07-07, challenge de Erika sobre escalas):** el brazo A
> suma `mom_24h` y `mom_72h` — se AGREGAN a las 4 escalas validadas, no las reemplazan
> (la regresión aprende el signo: continuación o reversal). Piso en 24h: por debajo es
> microestructura sobre velas de 1h, con fees > edge y ejecución 1×/día. Por el grado
> de libertad extra, n_trials del DSR: 18→**20**. También pre-run: nada corrido aún.

---

## 1. Objetivo y jerarquía de jueces

Un modelo de **regresión** que prediga el **retorno forward** (no el nivel de precio) por
símbolo, usando el momentum del campeón como una feature más — la hipótesis de Erika:
*"la magnitud y el contexto (régimen, volumen) contienen señal que el voto de signo tira"*.

- **El piloto (este experimento) decide UNA cosa:** si el challenger merece entrar al slot
  shadow. No toca al campeón, no toca producción, no gasta el holdout (ya quemado — §8.9 v2).
- **El juez de PROMOCIÓN a ejecutor** es el track record shadow acumulado contra el campeón
  con datos del futuro (`src/brain/shadow.py`, protocolo §8.9 v2) — nunca este backtest.
- Las **noticias** NO entran al piloto histórico (los RSS no tienen archivo; backtestearlas
  sería ficción). Entran **forward-only en shadow** si el challenger pasa (decisión Erika
  2026-07-07).

## 2. Por qué retornos y no "el precio de BTC con precisión"

Una regresión sobre **niveles** de precio da R² ≈ 0.99 gratis: el precio de mañana se
parece al de hoy (autocorrelación). Ese R² no contiene NINGUNA información tradeable —
predecir `precio_t+1 ≈ precio_t` no dice si comprar o vender. El contenido de trading
vive en el **incremento**: el retorno forward. Por eso el target es el retorno (donde el
R² será minúsculo y HONESTO), y "precisión del precio" se reformula como precisión del
retorno en unidades de volatilidad.

## 3. Setup (todo fijado a priori)

| Parámetro | Valor | Fuente |
|---|---|---|
| Universo | los 6 de la whitelist: BTC, ETH, SOL, LINK, AVAX, XRP (`*/USDT`, 1h) | cobertura verificada: bronze+silver completos 2021→2026-07, nulls solo warmup (199/499 velas) |
| Ventana de iteración | `2021-01-01 → 2025-06-28` | protocolo §1 — el holdout NO se toca (quemado por el campeón) |
| Horizontes (2 brazos) | **A: 24h** (decisión diaria, PPY=365) · **B: 7d** (decisión semanal `W-MON`, PPY=52, no solapado) | enmienda pre-run 2026-07-07 |
| Purga | 500h en ambos brazos (ventana GARCH — la feature rolling más larga) | `PURGE_PERIODS`, `quant_core.py:34` |
| Embargo | = horizonte del brazo: 24h (A) · 168h (B) — excluye outcomes no madurados | principio del embargo, `quant_core.py:35` |
| Fees | **36 bps/lado (primario — realidad Bitso taker)**; 10 bps secundario (comparabilidad con H6 histórico) | stress 2026-07-03 |
| Tubería económica — brazo B (7d) | `_evaluate` de `backtest.py`: allocator §8.8 (`compute_allocations`, libro vacío por período, `global_mult=1.0`), cap short 10% | idéntica a H5-H7 — comparación justa |
| Tubería económica — brazo A (24h) | **evaluación con estado (nueva, pre-registrada):** libro que PERSISTE día a día; targets del allocator §8.8 con `min_trade_frac=0.05` (valor de producción); órdenes = delta vs libro; **fees solo sobre el notional realmente operado** (no round-trip ficticio diario); mark-to-market diario | simula lo que producción hace — banda anti-churn incluida |
| Seed | 42 | reproducibilidad |
| Costo | $0 — sin LLM, sin GCP, sin red | data local `hermes.duckdb` |

**Target (por brazo):** `y = fwd_ret_H / max(garch_vol_asof × √H_horas, 1e-4)` — retorno
forward del horizonte en unidades de σ (vol GARCH horaria as-of escalada al horizonte:
√24 para A, √168 para B). Normalizar por vol hace el target comparable entre símbolos y
regímenes → habilita el modelo pooled. `fwd_ret` sale de `get_forward_return` (harness).

**Mapping señal (fijo):** `direction = sign(ŷ)` si `|ŷ| ≥ τ = 0.10` (dead-zone: una
predicción < 0.1σ es ruido, no opinión); si no → sin señal (HOLD). `conf = min(|ŷ|, 0.95)`
— ŷ está en σ, predecir un movimiento de 1σ ya es convicción máxima. `garch_vol` as-of
acompaña la señal para el inverse-vol del allocator, igual que todas las estrategias.

### 3.1 Horizonte (7d) vs cadencia — sin auto-boicot (pregunta de Erika, 2026-07-07)

Una predicción a 7 días es una apuesta que **madura en 7 días**; re-decidir a diario puede
matarla en el día 2 y pagar fees por operar ruido (la cota inferior de la auditoría de
cadencia: −93%). Cómo se maneja en cada ámbito:

- **En el piloto:** imposible por construcción. Brazo B: decisión cada lunes (W-MON), la
  apuesta vive sus 7 días intactos, períodos NO solapados. Brazo A: horizonte = cadencia
  (24h/diario) — la apuesta madura ANTES de la siguiente decisión, el desajuste desaparece
  de raíz (enmienda 2026-07-07, pregunta de Erika).
- **En el embargo de entrenamiento:** los outcomes que "aún no maduraron" a la fecha del
  fold quedan excluidos (`EMBARGO_PERIODS=168h`) — el modelo nunca estudia con respuestas
  que en vivo no tendría.
- **En shadow (si pasa):** el challenger emitirá señal diaria con horizonte 7d. Su score
  predictivo (IC) se computa contra el retorno realizado a 7d de CADA señal; la
  comparación ECONÓMICA contra el campeón se hace en períodos no solapados (submuestreo
  semanal) — señales diarias solapadas comparten el mismo movimiento y inflarían la
  estadística.
- **En producción (si algún día ejecuta):** hereda la maquinaria anti-churn existente
  (banda 5% + freeze + panel de turnover, decisión Erika opción B) y la revisión de
  cadencia de ~2026-08-05. Ese dilema es operativo y ya tiene juez propio; no se
  resuelve en este experimento.

## 4. Tabla de features (feature → hipótesis económica → ¿existe? → veredicto)

| Feature | Hipótesis económica | ¿Existe? | Veredicto |
|---|---|---|---|
| `mom_168h` (7d) | continuación de tendencia corta — el campeón como input (idea de Erika) | derivable de bronze | **ENTRA** |
| `mom_336h` (14d) | ídem, escala media | bronze | **ENTRA** |
| `mom_720h` (30d) | ídem, la escala H5 | bronze | **ENTRA** |
| `mom_2160h` (90d) | tendencia estructural | bronze | **ENTRA** |
| `mom_24h` | información fresca para el target diario; puede continuar O revertir — el signo lo decide la regresión, no nosotros | bronze | **ENTRA (solo brazo A)** |
| `mom_72h` | ídem, escala 3 días | bronze | **ENTRA (solo brazo A)** |
| `hurst` | trending vs mean-reverting: cuánto CONFIAR en el momentum (el kernel de mérito de H7: ayudó en 2022/2025) | Silver | **ENTRA** |
| `garch_vol` | el momentum rinde distinto en vol alta/baja; además interactúa con el sizing | Silver | **ENTRA** |
| `spread` | proxy de liquidez/estrés de mercado | Silver | **ENTRA** |
| `vol_z` — z-score de volumen: `(μ_vol_7d − μ_vol_90d) / σ_vol_90d` sobre volumen horario | expansión de volumen confirma tendencia; contracción la debilita — el aporte "subutilizado" identificado el 07-04 | **Bronze, nuevo** (única feature nueva del piloto) | **ENTRA** |
| retornos laggeados 1w | — | redundante: ES `mom_168h` | NO ENTRA |
| hora-del-día / día-de-semana | estacionalidad intradía | sin varianza en stamps semanales W-MON (constantes) | NO ENTRA — pertenece a un arco intradía futuro |
| noticias (clusters F4.0) | eventos mueven precio antes que el precio | sin archivo histórico | NO ENTRA — forward-only en shadow (decisión 2026-07-07) |
| polynomial features / seasonal_decompose centrado / niveles de precio | — | — | **PROHIBIDAS** (pre-registro 2026-07-04; el seasonal centrado FILTRA FUTURO) |

8 features (brazo B) / 10 (brazo A). Pocas y con hipótesis: el DSR cobra cada grado de
libertad — y las dos escalas cortas del brazo A ya lo pagaron subiendo n_trials a 20.

## 5. Escalera de modelos — 3 modelos × 2 brazos = 6 trials, ni uno más

Entrenamiento **pooled cross-symbol, por stamp**: en cada fecha de decisión se entrena
UN modelo con TODOS los puntos (símbolo, ts) anteriores que respeten purga+embargo
(≥ 100 puntos de train o se salta el stamp), y predice los 6 símbolos de esa fecha.
Brazo A: stamps diarios (~1,600 fechas). Brazo B: stamps semanales `W-MON` (~230).
Normalización `StandardScaler` **fit solo en el train del fold** (per-fold, como H7).
LightGBM no usa scaler (invariante a monotónicas). Nada se re-entrena con datos del futuro.

| Trial (× brazo) | Modelo | Features | Pregunta que responde |
|---|---|---|---|
| **T1** | Ridge (α=1.0) | solo las `mom_*` | ¿la MAGNITUD lineal del momentum agrega sobre el voto de signo del campeón? |
| **T2** | Ridge (α=1.0) | todas | ¿régimen + liquidez + volumen agregan linealmente? |
| **T3** | LightGBM regressor chico: `max_depth=3, n_estimators=300, learning_rate=0.05, min_child_samples=100, subsample=0.8, colsample_bytree=0.8, random_state=42` | todas | ¿no-linealidades e interacciones agregan? (la lección Exp. 0: en este problema el ML suele agregar solo varianza) |

- **Baseline predictivo:** media del train del fold (≈ 0). El R² OOS se mide contra eso.
- **Vara económica:** H6 multimom (`run_multiscale_momentum_backtest`) re-corrido en la
  MISMA ventana, mismos stamps, mismos fees — nunca los números históricos copiados.
- Los hiperparámetros de arriba NO se tunean. Si alguien quiere otro α u otro depth, eso
  es OTRO trial que suma al DSR de un experimento futuro.

## 6. Métricas y criterios de muerte/promoción (TODOS fijados antes de correr)

**Métricas predictivas (OOS, pooled):** IC de Spearman (ŷ vs y realizado) con p-value ·
R² OOS vs baseline media-train · hit rate direccional (sign(ŷ)=sign(y) donde |ŷ|≥τ).

**Métricas económicas:** Sharpe anual, PSR(0), DSR, retorno total, maxDD, skew, win rate,
por año y agregado — vía `_evaluate` con fee 36 bps (primario) y 10 bps (secundario).

**Contabilidad DSR:** `n_trials = 20` (conservador: 8 configs del Exp. 0 + el arco
H5–H8 + los 6 trials de este piloto + 2 por el grado de libertad de las escalas cortas
del brazo A). Fijado aquí; más alto = vara más dura.

**PROMOCIÓN a shadow** — un trial pasa solo si cumple **las 4 dentro de su brazo**
(la vara H6 se re-corre POR BRAZO bajo la evaluación idéntica: semanal `_evaluate` para
B; diaria con libro persistente + banda para A):
1. IC Spearman OOS > 0 con p < 0.05.
2. Sharpe anual (fee 36 bps) **>** el de H6 multimom en la misma ventana/cadencia/fees.
3. PSR(0) > 0.95 **y** DSR (n_trials=20) > 0.90.
4. Robustez anual: no pierde contra H6 en más de 2 de los 5 años calendario (que el edge
   no sea un solo año con suerte — la lección del front-loading 2021).
Si pasan trials en ambos brazos, a shadow va el del brazo A (24h — alineado a la
cadencia de producción); el otro queda documentado.

**MUERTE:** si ningún trial cumple las 4 → el arco "regresión sobre features de
precio/Silver" se cierra con entrada dónde-no-ir en el EXPERIMENT_LOG, y el único eje
vivo del challenger queda el de noticias forward-only en shadow (que no necesita esta
regresión para existir).

**Si PASA:** fase siguiente (separada, con Erika): integración al slot shadow
(`src/brain/shadow.py`) + [[project-silver-rework]] con columnas versionadas
(evolucionar, no reescribir — el campeón live depende de las columnas actuales).

## 7. Reproducibilidad

Script del piloto en scratchpad (el código de research no entra a `src/` hasta ganarse
la promoción — patrón del news lab F4.0), citado íntegro en la entrada H9 del
EXPERIMENT_LOG con seed y queries. Los números del log deben regenerarse corriendo el
script sobre `data/hermes.duckdb`.
