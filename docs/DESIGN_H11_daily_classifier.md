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
