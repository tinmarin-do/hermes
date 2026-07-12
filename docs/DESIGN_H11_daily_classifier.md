# DESIGN H11 — Clasificador binario diario, laboratorio 100% cloud (PRE-REGISTRO)

**Fecha de pre-registro:** 2026-07-11 · **Owner:** Erika (Product & Tech Lead)
**Estado:** ABIERTO — este documento se commitea ANTES del primer trial y las reglas
de abajo NO se cambian retroactivamente. Cambios = nueva versión fechada + razón.

## 1. Hipótesis y meta

Un clasificador binario (logística primero, LightGBM después) sobre features de
horizonte diario puede predecir **y = 1 si el retorno del símbolo en las próximas 24h,
medido en MXN, es > +1%**, con calidad suficiente para construir una cartera long-only
en Bitso que rinda ~1% diario neto de fees.

**Meta dual (la que libera el 20% final del presupuesto de créditos y detiene la
iteración):**
- **F1 ≥ 0.60 out-of-sample pooled**, cumplido en AMBAS validaciones del split híbrido
  (§4): media de los K sorteos por bloques Y corte temporal puro.
- **~1% diario neto MXN** en el backtest de estrategia (fees turnover 36 bps + slippage
  10 bps de sensibilidad).

Contexto honesto: base rate esperada p≈0.25-0.35 → F1 naive (siempre-sí) ≈ 0.40-0.52.
Antecedentes en contra: Exp. 0 (LightGBM P(fwd_7d>0)) y H7 (logística) FALSIFICADOS a
horizonte 7d. El horizonte 24h + moneda MXN + universo ampliado = trial nuevo, pero el
arco arrastra su conteo completo de trials para el DSR.

## 2. Datos (diseño dual, decisión 2026-07-11)

- **Binance = observar**: corpus histórico 1h, 29 símbolos USDT, 2021-01→hoy (delistados
  EOS/FTM/MKR/MATIC incluidos en entrenamiento — reducen sesgo de supervivencia — pero
  NO operables). Refresco SOLO por cable local (delta + upload; geo-block 451).
- **Bitso = medir**: libros MXN (17 activos, auditoría en
  `reports/bitso_universe_audit.md`), labels nativos donde su histórico alcance, y TODA
  la evaluación realizada/contabilidad. Refresco desde la nube.
- **FX**: USDMXN diario FRED DEXMXUS (ffill fines de semana) + libro `usdt_mxn` como
  serie del venue. Label sobre corpus Binance: `y = (1+r_usdt)(1+r_fx)−1 > 0.01`.
- **Puente pre-registrado** (`reports/venue_bridge.md`): por libro, en el traslape
  diario, mediana |Δr| ≤ 30 bps y corr ≥ 0.95 → lo entrenado en Binance transfiere.
  Libro fuera de umbral → decisión de Erika antes de usarlo.

## 3. Universo operable

Libros MXN de Bitso que pasen TODOS los filtros (evaluados en la auditoría):
completitud de velas ≥ 95% en los últimos 12 meses · volumen ≥ 1M MXN/día (media 30d) ·
historia ≥ 12 meses. La lista resultante se congela por versión de dataset.

## 4. Sample, split y validación (decisión #9 de Erika)

- **Resampleo**: 1h → diario anclado 00:00 UTC (barra D = [D 00:00, D+1 00:00); días
  con <20 velas se descartan). Dataset pooled cross-symbol: `datasets/daily_v1.parquet`.
- **Particiones firewall**: último **15%** del histórico = **slice de confirmación
  one-shot** (INTOCABLE; se evalúa UNA vez, §7). Resto = sample de iteración. Forward
  post-2026-07 = holdout virgen (shadow).
- **Split híbrido 80/20 sobre el sample de iteración**:
  (a) bloques MENSUALES contiguos sorteados a validation (~20%), purga 1 día + embargo
  5 días en cada frontera, **K=5 sorteos** (seeds deterministas) → F1 media±σ;
  (b) **corte temporal puro** (último 20% cronológico), misma purga/embargo.
  PROHIBIDO el split aleatorio por filas (leakage por autocorrelación). Scalers se
  ajustan SOLO en train de cada sorteo.
- **Regla de coherencia de ventanas (dura)**: la ventana de observación del information
  set es significativamente mayor que el horizonte (semanas/meses → 1 día). Ninguna
  variable con lookback efectivo ≤ 1 día como única señal.

## 5. Metodología de variables — SENSE FIRST (gate de Erika)

NADA de iterar variables a lo loco. Sobre un sample de estudio (3-5 libros
representativos), cada variable candidata pasa por: racional económico escrito →
distribución/outliers → estabilidad temporal (por año) → relación con el target (rate
de y=1 por decil, IC) → comportamiento por régimen → redundancia (corr/VIF) → canary
anti-leakage (valor en t con serie completa == con serie truncada en t).
**Entregable: `reports/feature_dossier.md`** (ficha por variable, veredicto propuesto).
**Erika aprueba el conjunto final — GATE D1→D2.** Catálogo inicial de candidatas: ver
plan del arco (retornos cortos, estructura intradía, cross-seccionales, régimen ligero
diario, calendario/quincenas, FX).

## 6. Conteo de trials y registro

TODO experimento (cada combinación modelo×hiperparámetros×umbral×dataset) se registra
como una línea en `experiments/trials.jsonl` (spec hash, métricas, timestamp) ANTES de
mirar su resultado. Ese archivo es la fuente de verdad de `n_trials` para el Deflated
Sharpe del backtest. Nada corre sin registrarse.

## 7. Firewall de promoción (NO iterable)

1. **Freeze** del candidato (spec hasheado + modelo entrenado solo con sample de
   iteración, guardado en `models/`).
2. **One-shot** en el slice de confirmación: sostener F1 ≥ 0.60 y retorno neto ≥ 0.5×
   el de validación. UN intento; si falla → slice quemado, se documenta, fin.
3. **Shadow forward ≥ 45 días** vía `persist_shadow_signals()` (cero cambios al grafo
   live) con F1 y P&L simulado consistentes con backtest.
4. **Sign-off explícito de Erika** → recién ahí se diseña el wiring a paper/live.
5. Veredicto (pase o falsificación) → `EXPERIMENT_LOG.md`.

El live (campeón momentum, ~$532 en Bitso) NO se toca durante el arco.

## 8. Presupuesto

$290 USD de créditos GCP (billing account MXN; budget real 4,900 MXN, alertas 50%/80%,
EXCLUDE_ALL_CREDITS). **Regla dura: jamás gastar >80% antes de la meta del §1.**
Ledgers markdown GCP suspendidos durante el arco (el budget real los reemplaza).

---

## 9. ENMIENDA v2 — target relativo (2026-07-12, aprobada por Erika: "Adelante")

**Razón (evidencia de trials 1-8, n_trials=8):** el target absoluto (>+1%) convirtió el
problema en market timing — el benchmark B&H equal-weight (+0.239%/día en el holdout)
domina a toda configuración; el exceso fue SIEMPRE negativo (mejor: −0.076%/día) y la
estrategia converge al mercado al suavizar la ejecución. La alta convicción no paga
(precision 0.52 en p>0.65 con bruto ≈ 0). F1 máximo observado 0.44 vs meta 0.60
(naive 0.51). Familia falsificada CON registro íntegro; el arco pivota a predicción
RELATIVA, donde el beta se cancela y el modelo compite contra sus pares, no contra
el mercado. Ping-pong completo con Erika 2026-07-12 (opción A + metas renegociadas).

### 9.1 Label v2 (`rel_median`)

`y = 1 si fwd_ret_24h_mxn(símbolo) > mediana(fwd_ret_24h_mxn de la canasta ese día)`.
- Canasta = todos los símbolos del corpus presentes ese día (mín. 5; días con menos se
  descartan). Derivado del MISMO `datasets/daily_v1.parquet` (sin re-ingesta).
- 50/50 por construcción todos los días, en todo régimen (día de crash: y=1 para los
  que caen menos). Sin class_weight ni artefactos de umbral.
- Encaje con la decisión: en producción ya elegimos top-k a diario; el label ES esa
  decisión. El slice de confirmación (últ. 15%, por fechas) queda intacto y aplica igual.

### 9.2 Metas v2 (reemplazan §1; deciden fin de iteración y liberan el 20% final)

- **Clasificación**: accuracy > 0.55 en AMBAS validaciones del split híbrido §4
  (media de K sorteos por bloques Y corte temporal). Naive = 0.50. AUC se reporta.
- **Económica ("ganancias >> pérdidas", Erika 2026-07-12)**: en el holdout temporal,
  **profit factor ≥ 1.5** (Σ días ganadores / |Σ días perdedores|) **y exceso vs B&H
  equal-weight > 0**. PSR/DSR siguen; n_trials NO se resetea (continúa del 8).
- Honestidad de escala pre-registrada: exceso realista esperado +0.05–0.15%/día si las
  cross-seccionales viven; puede salir 0 y se reporta igual. Relativo long-only en año
  bajista puede perder en absoluto — se reporta sin maquillar.

### 9.3 Variantes de estrategia v2

- **TP +3% ENTERRADO** (decisión #10 cerrada con evidencia): destruye configs ganadoras
  (+0.164 → −0.086%/día) — amputa la cola derecha que paga todo. Veredicto en
  EXPERIMENT_LOG; el watchdog upside NO se construye.
- **Nueva variante SIEMPRE-corrida: stop-loss −3%** (corta la cola IZQUIERDA — alineada
  con la meta de asimetría): si el low del día siguiente toca entrada×(1−sl), la pata
  sale a −sl + fee extra. Supuesto documentado: fill al nivel del stop (cripto 24/7,
  sin gaps overnight; velas 1h subyacentes). Ambigüedad de path (low y high el mismo
  día) se resuelve PESIMISTA: el stop dispara primero.

### 9.4 Mini-D1 sense-first (gate de Erika)

Antes de entrenar: re-juicio del catálogo COMPLETO de candidatas (las cross-seccionales
rel_ret_5d/breadth/etc. murieron contra el target absoluto — compitiendo contra ruido
de mercado, no contra pares) vs label v2, mismo protocolo del §5 (distribución,
estabilidad, y-rate por decil, IC, canary, redundancia) →
`reports/feature_dossier_v2_relmedian.md`. **Erika aprueba el conjunto v2 antes del
primer trial de entrenamiento.**

---

## 10. ENMIENDA v3 — label de extremos top-k (2026-07-12, aprobada por Erika: "VA!")

**Razón (tanda 3, trials 9-12):** rel_median dio la mejor config del arco (+0.169%/día,
Sharpe 1.25, DSR 0.38) pero con exceso bruto ≈ 0 sobre la canasta: acc 51.3% hecha de
aciertos SIN magnitud (empates pegados a la mediana). Diagnóstico: la frontera de
decisión vive en la zona más densa de la distribución cross-seccional. Además quedó
enterrado el SL-3% junto al TP-3% (±3% intradía = banda de ruido a vol diaria cripto;
ningún mecanismo de salida intradía a ese nivel sobrevive — dónde-no-ir del arco).

### 10.1 Label v3 (`extremes_k5`) — idea de Erika (top-k) + purga de la banda de ruido

- **y = 1 si el símbolo queda en el top-5 del día siguiente** (por fwd_ret_24h_mxn,
  rank cross-seccional del corpus); **y = 0 si queda en el bottom-5**; la banda media
  queda **NaN y fuera del TRAINING** (el modelo solo aprende contraste alto:
  "ganó por mucho" vs "perdió por mucho").
- 50/50 exacto por construcción (5 vs 5) — sin class_weight ni artefactos de umbral.
- Canasta mínima: **≥ 2k+1 = 11 símbolos/día**; días menores → NaN. Empates de rank:
  method="first" (determinista).
- **En la decisión se puntúa TODO el universo** (incluida la banda media que el modelo
  no vio en training — estándar del diseño de cuantiles extremos; el backtest juzga).
  Regla anti-leakage explícita: el backtest del holdout usa TODAS las filas con
  features válidas, jamás solo las que terminaron extremas (eso sería lookahead).

### 10.2 Metas y métricas (§9.2 transfiere + una nueva)

- accuracy > 0.55 en AMBAS validaciones **sobre filas extremas** (naive = 0.50).
- **precision@5 en el holdout temporal** (de los 5 elegidos por p, cuántos quedaron en
  el top-5 real; naive ≈ 5/N ≈ 24%) — métrica de decisión, se reporta siempre.
- Económicas sin cambio: profit factor ≥ 1.5 + exceso vs B&H > 0. PSR/DSR siguen;
  n_trials continúa (12 al momento de esta enmienda).

### 10.3 Estrategia

- **Variantes de salida intradía RETIRADAS** (TP-3% y SL-3% enterrados con evidencia,
  EXPERIMENT_LOG tandas 2-3). Se corre solo la estrategia base (suavizada).
- Conjunto de features: **FEATURE_SET_V2 tal cual** (aprobado para predicción relativa;
  el IC del dossier v2 se midió contra el retorno relativo, que no cambia — solo cambia
  qué filas enseñan). Splits, firewall y slice de confirmación intactos.
