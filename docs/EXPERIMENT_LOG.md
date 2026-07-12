# Experiment Log — Hermes (registro honesto de qué funciona y qué no)

> Bitácora de laboratorio. Cada experimento se anota con **hipótesis, setup, resultado OOS y
> conclusión** — incluidos (sobre todo) los resultados negativos. Esto es el mapa de **dónde NO
> ir**, y la cuenta de configuraciones probadas alimenta el **Deflated Sharpe** (anti data-snooping).
> Filosofía (README): el éxito es el proceso riguroso + la transparencia, reportar pérdidas incluido.

---

## Protocolo de iteración disciplinada (no negociable)

Para no caer en el data-snooping que el DSR castiga:

1. **Holdout final reservado — INTOCABLE.** `2025-06-28 → 2026-06-28` (últimos 12 meses) **NO se usa
   en NINGUNA iteración**. Toda exploración/walk-forward corre solo sobre `2021-01-01 → 2025-06-28`
   (~4.5 años). El holdout se toca **UNA sola vez**, al final, para validar el candidato ganador.
2. **Una variable por experimento.** Cambiar label, o features, o horizonte — nunca todo junto.
3. **Contar TODOS los intentos.** Cada fila de abajo suma a `n_trials` del DSR. Reportar siempre PSR(0)
   y DSR; un PSR alto con DSR bajo = overfitting por selección.
4. **Métrica de corte a priori.** Un candidato "pasa" solo si PSR(0) > 0.95 **y** DSR > 0.90 en
   walk-forward de iteración — y recién entonces se valida en el holdout.
5. **No tunear umbrales para subir el número.** Los umbrales (`P≤0.25/0.65`, Kelly, cap short) se
   fijan por diseño, no por búsqueda sobre el test.

---

## Experimento 0 — BASELINE (núcleo cuant LightGBM + allocator §8.8)

**Fecha:** 2026-06-28 · **Estado:** ❌ **SIN edge demostrable** (línea base de referencia).

**Hipótesis:** un LightGBM sobre features de régimen (Hurst, GARCH, spread, momentum) predice
`P(forward_return_7d > 0)` con edge suficiente para que el allocator genere retorno ajustado por riesgo.

**Setup:** purged + embargoed walk-forward (purge 500h, embargo 168h, horizonte 168h=7d).
5 majors (BTC/ETH/SOL/BNB/AVAX). Backtest de portafolio semanal no-solapado, budget $1,
`global_mult=1.0` (sin freno LLM — no backtesteable barato). PSR/DSR Bailey-López de Prado.

**Resultado — la historia corta MINTIÓ:**

| Métrica | 2.5 años (2024–26) | **5.5 años (2021–26)** |
|---|---|---|
| Señales OOS | 1492 | 3250 |
| BUY win rate | 56.4% (n=179) | **46.8%** (n=263) |
| Trade win dir-aware | 53.9% | **46.8%** |
| SELL disparos OOS | 12 | **0** |
| Backtest períodos | 21 | 41 |
| Retorno total | −2.35% | **−37.0%** |
| Sharpe anual | 0.33 | **0.011** |
| **PSR(0)** | 0.58 | **0.504** |
| **DSR (8 configs)** | 0.11 | 0.074 |
| Max drawdown | −48% | **−74.8%** |

**Conclusión / DÓNDE NO IR:**
1. **No confiar en ventanas cortas.** 2024–26 fue alcista; el sesgo largo del modelo "acertaba" por
   inercia de mercado, no por skill. Sumar 2021–22 (bear de 2022) derrumbó el win rate a <50%.
2. **`P(fwd_7d > 0)` con label binario crudo no tiene alpha** sobre un ciclo completo. PSR(0)=0.504 = moneda.
3. **El modelo tiene sesgo largo** y no aprende a anticipar caídas (los shorts ni disparan).
4. **El umbral de short `P≤0.25` es tan estricto que nunca se activa** (n=0 en 5.5 años) → política
   de short *dormida*, no validada. No perdió, pero tampoco aporta.
5. **El framework de medición (walk-forward purgado + PSR/DSR + holdout) SÍ funciona** — cazó el
   falso positivo antes de cualquier deploy. Eso se conserva; lo que se itera es el *modelo*.

---

## Experimento H5 — Control momentum no-ML (la vara)

**Fecha:** 2026-06-28 · **Estado:** 🟢 **el momentum DEMUELE al LightGBM** (resultado fuerte, a estresar).

**Hipótesis:** una regla trivial (largo si retorno-30d > 0, corto si < 0) por el **mismo allocator**
iguala o supera al LightGBM. Si lo supera, el ML no aporta edge.

**Setup:** `run_momentum_backtest`, lookback 720h=30d (fijo a priori, no tuneado), mismo allocator +
cap short 10% + horizonte fwd 7d, ventana de iteración `<2025-06-28`, 1 trial.

| Métrica | LightGBM (baseline) | **Momentum (H5)** |
|---|---|---|
| Períodos | 41 (silencioso) | **230** (opera casi siempre) |
| Retorno total | −37.0% | **+2131%** |
| Sharpe anual | 0.011 | **1.50** |
| **PSR(0)** | 0.504 | **0.9999** |
| **DSR** | 0.074 | **0.9999** (n_trials=1) |
| Max drawdown | −74.8% | **−36.9%** |
| Skew | −0.47 | **+1.76** (cola derecha) |

**Conclusión:** el **LightGBM no solo no aporta — es PEOR que una regla de una línea.** El momentum,
al flipear a corto/cash en downtrends, evita el bear de 2022 y cabalga los bulls → Sharpe 1.5, skew
positivo, menos drawdown. **El alpha (en este universo/era) está en trend-following, no en el ML direccional.**

⚠️ **A ESTRESAR antes de creérselo (Sharpe 1.5 es sospechosamente bueno):**
1. **Sin costos de transacción** — el rebalanceo semanal tiene turnover; con fees baja.
2. **Survivorship bias** — los 5 majors son sobrevivientes conocidos (SOL/AVAX explotaron). Sesga el momentum al alza.
3. **Era excepcionalmente trendy** — 2021-2025 fue la época dorada del momentum cripto. El **holdout 2025-06→2026-06 (intocado)** es el juez real.
4. Kurtosis 10.8 → colas gordas; el retorno depende de pocos movimientos grandes.

**Implicación para el plan:** H4 (rescatar el LightGBM con features de downside) y H1 (relabel) pierden
prioridad — no tiene sentido invertir en un modelo que pierde contra un one-liner. El pivote racional es
**estresar + endurecer el momentum**, no arreglar el ML. (Confirmado por Erika → pivote a estresar.)

### H5-stress — el globo se pincha (foto sobria)

| Test | Resultado | Lectura |
|---|---|---|
| **Costos** (fee/side 0→0.2%) | Sharpe 1.50→**1.40** (10bps), 1.30 (20bps) | ✅ **sobrevive a fees** (poco turnover, holdea tendencias) |
| **Sensib. lookback** (14d/30d/60d) | Sharpe **0.63 / 1.40 / 0.64** | 🔴 **bandera roja:** el 30d es un pico; los vecinos son mediocres → el 1.40 es en parte *suerte de parámetro* |
| **Por año** | 2021 **+805%** · 2022 **−27%** · 2023 +149% · 2024 +7.5% · 2025 −1.7% | 🔴 **front-loaded por 2021**; 2022 fue PÉRDIDA (el cap short no protege el bear); **2024-25 planos** |
| **Equity** | 1→9.05→6.59→16.4→17.7→**17.4** | el edge **decae**: casi todo fue 2021+2023; 2024-25 chato |

**Conclusión honesta:** el momentum tiene un edge **real pero modesto y decreciente**, NO el slam-dunk del
número crudo. El Sharpe robusto (descontando suerte de lookback) es ~0.6-0.7, **dominado por la alt-season
2021**, plano desde 2024. **No protege en bear** (2022 perdió −27%). Mi hipótesis previa ("flipea a corto
y gana en el bear") era FALSA — el cap short 10% lo impide.

**Dónde NO ir (actualizado):**
6. **No confiar en el Sharpe crudo de una sola config** — el stress (lookback, por-año, costos) es obligatorio.
7. **El edge de momentum cripto decae** post-2021; un número alto puede ser una era irrepetible.
8. **El cap short 10% deja sin protección de bear** — revisar si se quiere capturar downside de verdad.

**Próximo:** el holdout 2025-06→26 (intocado) es el juez final. Dado que 2024-25 ya vienen planos, se espera
poco edge vivo — pero validarlo es el cierre riguroso. (Decisión: ¿gastar el holdout ahora?)

---

## Experimento H6 — Momentum multi-escala (voto 7/14/30/90d), regla sin ML

**Fecha:** 2026-06-28 · **Estado:** 🟡 robusto pero **NO supera al single-30d; el decaimiento persiste**.

**Hipótesis:** votar el signo del momentum en 4 escalas (7/14/30/90d) es más robusto que una sola
ventana (el single-30d era suerte de parámetro: 14d→0.63, 60d→0.64). Perf 7d, mismo allocator, `<2025-06-28`.

| Estrategia (fee 0.1%/lado) | Sharpe | PSR | ret | maxDD | skew | win |
|---|---|---|---|---|---|---|
| **multi-escala 7/14/30/90** | **1.20** | 0.999 | +987% | −44% | +2.16 | 0.49 |
| single-30d (ref) | 1.40 | 1.000 | +1635% | −39% | +1.75 | 0.53 |

**Por año (multi-escala vs single):**
| Año | single-30d | multi-escala |
|---|---|---|
| 2021 | +805% | +642% |
| 2022 | −27% | −21.7% |
| 2023 | +149% | +81% |
| 2024 | +7.5% | **+23.6%** |
| 2025 | −1.7% | **−16.3%** (win 0.28) |

**Conclusión:** multi-escala compra **robustez** (no depende de un lookback con suerte) a costa de
**performance** (Sharpe 1.20 < 1.40). PERO **el problema de fondo NO se resolvió**: ambas siguen
front-loaded por 2021, pierden en 2022, y **decaen** — 2025 es negativo para las dos (peor para multi-escala,
−16%, win 0.28). Reshufflear la ventana de momentum no arregla el decaimiento; **el edge de momentum
cripto es un fenómeno 2021-2023 que se está yendo del mercado.**

**Dónde NO ir (actualizado):**
9. **El decaimiento no es problema de lookback** — single vs multi-escala da igual; el edge se está agotando.
10. **Ninguna regla de momentum condiciona por RÉGIMEN** — la única palanca sin probar: ¿cash en mean-reverting?

---

## Experimento H7 — Logística regime-conditioned (mom 7/14/30/90 + hurst/garch)

**Fecha:** 2026-06-28 · **Estado:** ❌ **DESCARTADA** por criterio de muerte a priori (no se la ganó).

**Hipótesis:** una logística que condicione el momentum por régimen ("confiá si trendea, cash si
revierte") frena el decaimiento 2024-25. Walk-forward purgado, una logística por punto, perf 7d, `<2025-06-28`.

**Criterio de muerte (fijado ANTES de correr):** gana solo si Sharpe>1.20 **Y** mejora 2024 **Y** 2025 **Y** PSR>0.95 ∧ DSR>0.90.

| | logística | regla multi-escala (vara) |
|---|---|---|
| Sharpe | **0.43** ❌ | 1.20 |
| PSR / DSR | 0.775 / **0.223** ❌ | 0.999 / 0.893 |
| 2024 | **−52.4%** 💥 | +23.6% |
| 2025 | +4.9% ✅ | −16.3% |
| 2022 | −9.9% ✅ | −21.7% |

**Resultado:** **se descarta** (falla las 3 condiciones). Matiz honesto: el regime-conditioning **tuvo un
kernel de mérito** — mejoró 2022 y 2025 (los años choppy/bear). Pero **explotó en 2024 (−52%)**, un año que
la regla ganó +24%: el modelo hizo llamadas de régimen catastróficamente erradas. Net: Sharpe 0.43 << 1.20.

**Dónde NO ir (actualizado):**
11. **El ML pierde otra vez contra la regla** (logística Sharpe 0.43 vs regla 1.20) — 3er modelo que no aporta.
    En este problema, la **regla simple gana**; el ML solo agrega varianza.
12. **Regime-conditioning vía clasificación binaria no funciona** — ayuda en bear pero rompe en bull (2024).

**CONCLUSIÓN DEL ARCO H5→H7:** el mejor candidato es la **regla de momentum multi-escala** (Sharpe 1.20,
PSR 0.999, robusta al lookback). El ML está descartado (3 intentos). El edge es **real pero decreciente**
(2024-25 flojos), front-loaded por 2021, sin protección de bear. Candidato listo para el holdout.

---

## VEREDICTO FINAL — Holdout 2025-06-28 → 2026 (data 100% nunca vista, 1 sola bala)

**Fecha:** 2026-06-28 · Candidato: **regla momentum multi-escala** (la única que sobrevivió el arco).

| | Candidato (multi-escala) | Benchmark (buy&hold equal-weight) |
|---|---|---|
| n (semanas) | 51 | 51 |
| Retorno total | **+2.2%** | **−40.4%** |
| Sharpe anual | **0.22** | −0.74 |
| PSR(0) / DSR | 0.585 / 0.106 | 0.232 / — |
| Max drawdown | **−27%** | −63% |

**El holdout fue un CRASH de cripto** (el mercado perdió −40% con −63% de drawdown). Veredicto de dos caras:

1. **❌ Sin edge ABSOLUTO significativo.** Sharpe 0.22, **PSR(0) 0.585** (casi moneda), DSR 0.106. Como
   predijimos (2024-25 venían planos), **no podemos afirmar con confianza estadística que genere retorno.**
   El +2.2% podría ser ruido.
2. **✅ Valor DEFENSIVO real y grande.** En un año que el mercado se desplomó −40%, el candidato quedó
   **plano (+2%) con la MITAD del drawdown** (−27% vs −63%). Sidesteppeó el crash. Sharpe 0.22 vs −0.74 del mercado.

**Conclusión honesta (cierre del arco):** la regla de momentum **no es una máquina de alpha** — su retorno
absoluto no es estadísticamente distinguible de cero. PERO se comporta como un **overlay defensivo / "crisis
alpha"**: preserva capital en bear markets, que es la propiedad clásica y documentada del time-series momentum
(estrategia convexa). Validado out-of-sample en un crash real.

**Qué dejó el proyecto (todo honesto y medido):**
- El **ML no aporta** en este problema (3 modelos, 3 derrotas vs regla simple).
- El **framework de medición** (walk-forward purgado + PSR/DSR + holdout reservado) **funciona** — cazó 1 falso
  positivo (LightGBM baseline) y dimensionó honestamente el momentum (espejismo de Sharpe 1.5 → realidad defensiva).
- El candidato desplegable es **defensivo, no ofensivo**: úsese como protección de drawdown, no como generador de retorno.

**Dónde NO ir (final):**
13. **No vender el momentum como alpha** — su valor probado es defensivo (downside protection), no retorno absoluto.

---

## Experimento H8 — Cross-sectional momentum (rankear los símbolos ENTRE SÍ)

**Fecha:** 2026-06-28 · **Estado:** ❌ **muere en iteración** (DSR < 0.90 a priori) · 🐛 **bug de timezone hallado y corregido**.

**Hipótesis:** un eje **ortogonal** al time-series momentum — rankear los 5 majors por retorno
trailing y ir **long los más fuertes / short los más débiles** — gana del *spread* ganador-perdedor,
así que puede pagar aunque el mercado esté plano o cayendo. Es el alpha cross-sectional documentado
(Jegadeesh-Titman). Si el spread market-neutral tiene edge, es retorno absoluto, no solo defensa.

**Setup (fijo a priori, NO tuneado):** lookback 30d (=H5), top-2/bottom-2 de 5, equal-weight por
sleeve, perf 7d, fee 10bps/lado, `<2025-06-28`, n_trials=10. Dos variantes: **market-neutral**
(long+budget/2, short−budget/2 → gross=budget, net=0; spread puro, **bypassa el cap short 10%** a
propósito — primero medir si el alpha existe) y **long-only** (solo top-2, desplegable en spot).

| Variante | Sharpe | PSR(0) | DSR | ret | maxDD | win | skew |
|---|---|---|---|---|---|---|---|
| **market-neutral (spread)** | 0.50 | 0.865 | **0.29** ❌ | +76% | −61% | 0.49 | +1.58 |
| **long-only (top-2)** | 1.15 | 0.998 | **0.84** ❌ | +2430% | −80% | 0.55 | +2.37 |

**Conclusión:**
- **El spread market-neutral — el test honesto de alpha ortogonal — es DÉBIL** (Sharpe 0.50, DSR 0.29).
  El ranking ganador-vs-perdedor **no agrega alpha tradeable robusto** en este universo.
- El Sharpe alto del long-only (1.15) es **beta de mercado + concentración**, NO alpha neutral:
  maxDD −80%, vol enorme, es literalmente "holdear los 2 majors más fuertes". Misma enfermedad de
  beta que el TS momentum; y DSR 0.84 igual no llega a 0.90.
- **CAUSA RAÍZ — el universo es la restricción, no la señal.** 5 majors ultra-correlacionados
  (~0.7-0.9). El cross-sectional necesita **dispersión amplia y diversa** para explotar; long-2/short-2
  de 5 nombres correlacionados deja un spread casi nulo.
- Por el protocolo a priori (DSR>0.90 para tocar el holdout), **se descarta en iteración. Holdout NO gastado.**

🐛 **Bug de timezone (hallado y corregido acá):** el backtest pasaba stamps **tz-aware UTC** a DuckDB,
que los convertía a la tz local del host (**UTC−6**), corriendo **6h cada lookup as-of**. Era **benigno**
para H5/H6 (el shift afectaba trailing Y forward por igual = rebalanceo a otra hora, internamente
consistente) pero real. Corregido **en la fuente** (`_iteration_stamps` hace strip de tz → todo el
stack naive-UTC en la hora verdadera). Los números del campeón (multiescala) conviene **re-validarlos**
a la hora correcta. Además: las reglas ahora **cachean la serie de precios en memoria** (sin abrir una
conexión DuckDB por lookup) → iteración mucho más rápida.

**Dónde NO ir (actualizado):**
14. **Cross-sectional sobre un universo chico y correlacionado = sin alpha ortogonal.** El Sharpe del
    long-only es beta disfrazada. Hipótesis a testear: ¿un universo **más amplio y diverso** lo rescata?

### H8-wide — universo ampliado a 28 nombres → **FALSIFICA la hipótesis del universo**

**Fecha:** 2026-06-28 · **Estado:** ❌ ampliar el universo **NO rescata** el cross-sectional.

**Setup:** backfill de bronze 2021→2026 de **23 alts** (XRP ADA DOGE DOT ATOM NEAR ALGO FTM TRX EOS
LINK UNI AAVE MKR SNX COMP LTC BCH ETC XLM FIL SAND MANA — varios colapsaron −90% en 2022, buena
dispersión; FTM/EOS/MKR con historia parcial por delisting). Universo total **28**. Quintil long-short
(top-5/bot-5), lookback 30d, equal-weight, perf 7d, fee 10bps, `<2025-06-28`. La regla cross-sectional
sólo usa precios → bronze alcanza (nuevo `_bronze_stamps`/`price_only`, sin correr Silver).

| Spread market-neutral | Sharpe | PSR(0) | DSR | maxDD | avg_legs |
|---|---|---|---|---|---|
| 5 majors | 0.50 | 0.865 | 0.29 | −61% | 4.0 |
| **28 nombres** | 0.53 | 0.876 | **0.31** | −37% | 9.9 |

**Conclusión:** el spread **apenas se movió** (Sharpe 0.50→0.53, DSR 0.29→**0.31**, sigue lejísimos de
0.90). Lo único que mejoró fue el drawdown (−61%→−37%, por diversificación). **La hipótesis "la
restricción es el universo" queda FALSIFICADA:** con 28 nombres diversos el ranking ganador-perdedor
tampoco tiene alpha. El long-only top-5 (Sharpe 1.01, maxDD −84%) sigue siendo beta concentrada.

**Cierre del arco cross-sectional:** 4 ejes probados (ML ×3, TS momentum, regime-logística,
cross-sectional narrow+wide) convergen en lo mismo — **sobre cripto líquida no hay alpha direccional
absoluto robusto con señales de precio; el único valor validado es defensivo** (overlay de momentum).
El método honesto y desplegable que la evidencia soporta es el overlay defensivo, no un generador de alpha.

**Dónde NO ir (actualizado):**
15. **Ampliar el universo no crea alpha cross-sectional** donde no lo hay — el spread quedó plano con 28
    nombres. La debilidad es de la señal de precio, no del tamaño del universo. (Variante canónica sin
    probar: momentum "12-1" con *skip* de la última semana para evitar reversal — única bala a priori que queda.)

---

## Lab Fase 4.0 — Selección de embedding + clustering para noticias (§8.7)

**Fecha:** 2026-07-02 · **Tipo:** experimento de infraestructura (no direccional — no suma a `n_trials`
del DSR de trading). **Decisión de Erika:** validar ANTES de la ingesta al medallón, con inspección
visual 2D ("seleccionar clustering es como seleccionar aguacates" — y tiene razón: sin ground truth,
las métricas descartan lo malo y el ojo decide entre lo bueno).

**Setup:** 391 titulares únicos de 15 feeds RSS ($0, seed 42) · 4 modelos de embedding × pipeline
idéntico (UMAP 10d cosine, n_neighbors=15, min_dist=0.0) × 18 configs de clustering (KMeans/
Agglomerative k=4..12, HDBSCAN mcs=5..20, DBSCAN eps=0.3..1.2) · Silhouette/Davies-Bouldin/
Calinski-Harabasz/DBCV/noise + t-SNE 2D con keywords por cluster (c-TF-IDF).

| Modelo | Mejor sil | DBCV | Visual (HDBSCAN mcs=10) |
|---|---|---|---|
| **all-MiniLM-L6-v2** ✅ | **0.702** | 0.485 | 12 clusters nítidos e interpretables |
| all-MiniLM-L12-v2 | 0.645 | **0.507** | ~igual a L6, 2× más lento |
| bge-small-en-v1.5 | 0.621 | 0.477 | fusiona regulación+sanciones (grueso) |
| all-mpnet-base-v2 | 0.635 | 0.432 | **COLAPSA a k=2** (375 en un pegote) |

**Hallazgos:**
1. **SÍ hay estructura clusterizable** — y los clusters calcan las categorías a priori del PRD:
   regulación (MiCA/FCA, 9 fuentes), hacks (`bridge/exploited`), macro (jobs/inflation), eventos
   corporativos multi-fuente (Metaplanet 7 fuentes, Strategy 7 fuentes → corroboración natural
   para `trust_score`), TA de precio, RWA/tokenización.
2. **El modelo grande pierde:** mpnet-base (768d, 4× más lento) colapsó con HDBSCAN y quedó último
   en silhouette-por-método. En titulares cortos, los modelos chicos rinden igual o mejor.
3. **Densidad >> partición:** KMeans/Agglomerative producen pegotes de 70-100 noticias mezcladas;
   DBSCAN fragmenta (25 microclusters, 34% ruido, eps frágil). HDBSCAN mcs=10: k=12, ruido 17%.
4. El **ruido ~17% es señal, no bug**: historias únicas sin cluster = el trigger de drift del PRD.

**DECISIÓN (Erika, con figuras a la vista):** `all-MiniLM-L6-v2` + `HDBSCAN(min_cluster_size=10,
min_samples=5)` sobre UMAP 10d cosine. Fijado en `news_transform.py` + `.envrc` — el método ya NO
se re-elige por corrida (comparabilidad de clusters); el arnés queda como auditoría.
**Caveat anotado:** parte de la estructura es estilo editorial (cluster memecoins mono-fuente u.today)
— mitigar con dedupe cross-fuente. Artefactos: scratchpad `news_lab.py` + figs en dashboard static.

---

## Stress adicional — fees a nivel Bitso (venue de ejecución decidido 2026-07-03)

**Fecha:** 2026-07-03 · **Tipo:** stress del champion existente a fee nuevo (no suma `n_trials`).

**Contexto:** la ejecución pasa a **Bitso** (taker 0.36%/lado, maker 0.30% — vs 0.10% Binance).
El stress original (H5) llegaba a 20bps; se re-midió el champion (multimom, `<2025-06-28`, 5 majors)
a **36bps/lado**:

| fee/lado | Sharpe | PSR(0) | maxDD |
|---|---|---|---|
| 10bps (ref) | 1.20 | 0.999 | −44% |
| **36bps (Bitso taker)** | **0.88** | 0.981 | **−60%** |

**Conclusión:** el edge **sobrevive pero adelgaza** (~27% menos Sharpe, drawdown peor). Mitigación
operativa para F6: **órdenes maker/limit** (0.30%) cuando sea posible, damper `min_trade` ya activo,
y recordar que la claim desplegada es DEFENSIVA (estar en cash durante crashes no paga fees).
**Dónde no ir #16:** no asumir los fees del backtest — el venue real los fija; re-stressear al cambiar de exchange.

---

## Registro operativo — PRIMER TRADE LIVE (F6, día 1 de la era-$400)

**Fecha:** 2026-07-03 · **Tipo:** operación (no experimento — no suma a `n_trials`).

**BUY 0.24383804 SOL/USDT @ $82.335 = $20.08 · fee $0.07 (taker 0.36%) · Bitso spot ·
run `live-validation-1`.** Orden mínima de validación del pipe (decisión del día: capital
cloud $400; el primer trade se dimensionó chico a propósito). Señal: champion momentum
SOL BUY conf 0.95 / P=0.975; comité del día (run `ccec96c6`) verdict BUY conf 80% risk ✓.
Guardrails calibrados el mismo día (`/brain:calibrate-risk` sobre momentum: Kelly=0.10
confirmado, loss limit 4%).

Saga honesta del camino (todo cazado por diseño — gates, orden chica, verificación):
1. **Key con restricción de IP** (Erika la limitó al "server local" — IP equivocada) →
   `Invalid Nonce or Invalid Credentials`. Rotada sin restricción; keys viven SOLO en
   Secret Manager, resueltas por `get_secret()` a memoria de proceso.
2. **Maker no llenó en 45s** (libro SOL/USDT de Bitso poco profundo) → fallback taker
   funcionó. A observar: si el maker-first casi nunca llena, el fee promedio real es
   0.36%, no 0.30% — el stress de fees usó taker, así que sin sorpresa.
3. **Bug del adapter cazado por la orden de validación:** Bitso responde el
   `create_order` market SIN `filled` (asíncrono) → el adapter declaró REJECTED una
   orden que SÍ llenó. Fix: re-consulta la orden real antes de declarar rechazo. Este
   bug en una corrida full-size hubiera dejado el libro contable divergido del real.

## Registro operativo — SWITCH DE SEÑAL EN PRODUCCIÓN (Fase 1, PRD v0.3)

**Fecha:** 2026-07-02 · **Tipo:** operación (no experimento — no suma a `n_trials`).

Consecuencia directa del veredicto del arco H0–H8: la señal ejecutora del pipeline pasa de
**LightGBM (falsificado, Exp. 0)** a la **regla momentum multi-escala (H6, validada en holdout
como overlay defensivo)**.

- **Champion:** `src/brain/quant_rule.py` — mismo voto de signo 7/14/30/90d del backtest H6,
  mismo contrato `QuantSignal` (P mapeado con la inversa de `_prob_to_signal`, preserva la
  equivalencia asimétrica del short conf≥0.50 ⟺ P≤0.25). El gate de short del nodo
  (conf + confirmación de régimen bajista) queda intacto.
- **Shadow (§8.9):** el LightGBM/heurística sigue corriendo por corrida como challenger
  placeholder; sus señales se persisten en la tabla `shadow_signals` (DuckDB) vía
  `src/brain/shadow.py` y **jamás ejecutan**. Este track record hipotético es el juez del
  protocolo v2 para cualquier candidato futuro (p. ej. la regresión continua).
- El slot shadow queda listo para el challenger de regresión sin tocar el grafo.

> Cada una se corre solo sobre datos de iteración, cuenta para `n_trials`, y se anota acá.

- **H1 — Label triple-barrier / meta-labeling (López de Prado):** reemplazar `fwd>0` binario por
  barreras (TP/SL/tiempo) ajustadas por volatilidad. Hipótesis: el label binario crudo es ruido; un
  label que respeta riesgo/horizonte tiene más señal. *(candidato #1 — el problema más probable es el label)*
- **H2 — Horizonte:** probar 24h / 72h en vez de 7d (el 7d fijo puede no matchear los regímenes).
- **H3 — Modelos condicionados por régimen:** un modelo por régimen en vez de uno global.
- **H4 — Features de downside:** agregar señales que capten caídas (drawdown rolling, asimetría) para
  romper el sesgo largo.
- **H5 — Enfoque no-ML de control:** trend-following / momentum puro como baseline honesto — si le gana
  al LightGBM, el ML no estaba aportando.

**Próximo:** definir con Erika cuál arrancar (recomendado: H1).

---

## Auditoría de cadencia — ¿la ejecución diaria está respaldada? (revisión final 2026-07-06)

**Fecha:** 2026-07-06 · **Tipo:** auditoría de coherencia validación↔producción (no suma a `n_trials`
como candidato nuevo; reutiliza la regla H6 ya absorbida). **Origen:** pregunta de Erika.

**Hallazgo:** el champion fue validado con rebalanceo **SEMANAL** (`freq="W-MON"`,
`PERIODS_PER_YEAR=52`, forward 168h) — pero producción evalúa y puede operar **DIARIO**
(Scheduler 08:10 MX). La cadencia diaria era una variante sin evidencia propia.

**Medición (2024-01→2026-07, misma ventana, periodos NO solapados en ambos):**

| Variante | n | Total | Sharpe | PSR | maxDD |
|---|---|---|---|---|---|
| Semanal validado, fees 36bps | 121 | −23.9% | −0.09 | 0.44 | −48% |
| Diario cota SUPERIOR (fwd 24h, PPY 365, fee 0) | 834 | +99.8% | 1.12 | 0.95 | −27% |
| Diario cota INFERIOR (round-trip completo 36bps/día) | 834 | −93.4% | −3.56 | 0.00 | −94% |

**Lectura:** evaluar diario APORTA señal (cota superior ≫ semanal); lo letal es el CHURN.
La producción real (allocator por deltas + freeze del comité) vive entre las cotas; su
posición exacta depende de la banda mínima de trade, que era 1% (solo filtraba polvo).

**Decisión (Erika, opción B):** cadencia diaria se mantiene CON banda anti-churn seria —
`min_trade_frac` 1%→**5%** (`HERMES_MIN_TRADE_FRAC`) + **panel de turnover/fees por mes**
en el snapshot. **Juez: el track record vivo (§8.9)** — revisar en ~30 días: si los fees
mensuales ≫ lo que ~4 rebalanceos semanales pagarían, alinear a semanal estricto (trades
solo lunes; el re-run de emergencia del watchdog conservaría permiso diario como capa
defensiva).

**Caveats honestos:** ventana 2024+ es iteración (holdout quemado, §8.9 v2); la cota
inferior asume re-alocación completa diaria (peor caso que el allocator real no hace);
el semanal-con-fees negativo en esta ventana es consistente con la claim (sin alpha
absoluto — PSR 0.44 ≈ cero) y con que 2024-2026 incluye régimen alcista donde el overlay
defensivo long-only queda atrás del mercado.

---

## Experimento H9 — Challenger de REGRESIÓN sobre precio+Silver (piloto, 2 brazos)

**Fecha:** 2026-07-07 · **Estado:** ❌ **FALSIFICADO — los 6 trials mueren por los criterios
a priori.** · **Pre-registro:** `docs/DESIGN_regression_challenger.md`, commit `48c3116`
(ANTES de cualquier resultado; 2 enmiendas pre-run de Erika, ambas fechadas). Suma **+6 a
n_trials** (DSR corrido con n=20, fijado a priori).

**Hipótesis (Erika):** una regresión del retorno forward (vol-normalizado) con la MAGNITUD
del momentum multi-escala + régimen (hurst/garch/spread) + volumen (vol_z, feature nueva)
supera al voto de signos del campeón. **Secuencia pilot-first decidida por ella:** piloto
barato ANTES de invertir en el rework de Silver.

**Setup:** 6 símbolos whitelist, 2021-01→2025-06-28 (holdout intocado), pooled cross-symbol,
fit por stamp, purga 500h + embargo=horizonte, scaler per-fold, seed 42. Brazo A: 24h diario,
evaluación CON ESTADO nueva (libro persistente + banda 5% + fees sobre turnover real — lo que
producción hace). Brazo B: 7d semanal `_evaluate` (idéntico a H5-H7). Dead-zone τ=0.1σ,
conf=min(|ŷ|,0.95). Scripts + resultados: `research/h9/` (commiteados para reproducibilidad
— única desviación del pre-registro §7, que decía scratchpad efímero; a favor del espíritu).

**Vara (campeón H6 re-corrido, MISMA tubería/universo/fees — no números históricos):**

| Vara H6 @36bps | Sharpe | PSR | n | maxDD | Nota |
|---|---|---|---|---|---|
| Brazo B semanal | **0.926** | 0.964 | 169 sem | −53% | ≠ log histórico (1.20@10bps con 5 majors viejos): universo actual LINK/XRP + fix tz H8. Hoy: 1.233@10bps |
| Brazo A diario | **0.927** | 0.976 | 1623 d | −62% | turnover 24.5%/día = **fee drag ~32%/año** — la banda 5% paga exactamente su costo (a 10bps el diario gana: 1.43 vs 1.23) |

**Resultados del challenger (fee 36bps primario):**

| Trial | IC Spearman (p) | R² OOS | hit rate | Sharpe | PSR | DSR n20 | vs vara |
|---|---|---|---|---|---|---|---|
| T1_A Ridge-mom diario | −0.004 (0.68) | −0.002 | 0.459 | **−0.19** | 0.35 | 0.01 | 💀 |
| T2_A Ridge-full diario | +0.017 (0.11) | −0.004 | 0.511 | **−0.13** | 0.40 | 0.02 | 💀 |
| T3_A LGBM diario | +0.006 (0.56) | −0.035 | 0.498 | **−0.94** | 0.03 | 0.00 | 💀 (fee drag 78%/año) |
| T1_B Ridge-mom semanal | **−0.067 (0.020)** | −0.016 | 0.471 | **−0.41** | 0.26 | 0.01 | 💀 |
| T2_B Ridge-full semanal | **−0.109 (1.6e-4)** | −0.036 | 0.433 | **−0.65** | 0.14 | 0.00 | 💀 |
| T3_B LGBM semanal | −0.020 (0.48) | −0.094 | 0.479 | **−0.10** | 0.43 | 0.02 | 💀 |

Ni un solo criterio de los 4 se cumple en ningún trial (la vara pedía Sharpe > 0.93 con
IC>0 significativo, PSR>0.95, DSR>0.90, robustez anual). A 10bps tampoco: el mejor
challenger (T2_A, Sharpe 0.42) queda a un tercio del campeón (1.43). El R² OOS es
negativo en los 6: predicen PEOR que la media del train.

**El hallazgo con contenido (no solo "no funcionó"):** el IC semanal de los Ridge es
**significativamente NEGATIVO** (T2_B: −0.109, p≈0.0002, n=1206). La magnitud lineal del
momentum ANTI-predice el retorno de la semana siguiente — consistente con reversal tras
movimientos grandes. El SIGNO (campeón) informa; la MAGNITUD extrapola justo al revés.
⚠️ **Tentación prohibida:** "flipear el signo del modelo" = hipótesis nueva post-hoc sobre
el mismo dataset — data snooping de libro. Si alguien la quiere, es pre-registro nuevo,
trial nuevo, DSR más caro. NO se hace en caliente.

**Conformidad post-auditoría (2026-07-07, noche):** la auditoría de Erika (estaciones:
features 11/11 exactas vs SQL independiente, alineación de ventanas 200/200, corr f↔y
0.006-0.04 sin leakage) encontró UN hallazgo real: el piloto omitió el **dummy de
símbolo** que el pre-registro §5 exigía. Re-run de los 6 trials con la spec exacta
(`pilot_results.json`; el original sin dummies quedó en
`pilot_results_sindummy_original.json`): **veredicto RATIFICADO** — mejor Sharpe36
0.21 (T1_A; vara 0.93), R² OOS negativos ×6, IC semanal sigue significativamente
NEGATIVO (T2_B −0.109, p=1.5e-4). Ningún criterio se cumple en ningún trial.

**Conclusión / DÓNDE NO IR (actualizado):**
16. **La regresión sobre features de precio+Silver está FALSIFICADA en ambos horizontes**
    (24h y 7d) — 6 trials, cero criterios cumplidos. Con este universo/era, la magnitud
    del momentum, el régimen y el volumen NO contienen señal direccional explotable que
    el voto de signos no tenga ya. Es la derrota #4-#6 del ML direccional (acumuladas:
    LightGBM clasificador, logística, cross-sectional ×2, regresión ×6 trials).
17. **No perseguir el IC negativo sin pre-registro** — el reversal de magnitud semanal es
    real en iteración (p=0.0002) pero nace muerto si se caza post-hoc.
18. **El eje vivo del challenger queda en NOTICIAS forward-only en shadow** (F4.0 validada,
    jamás usada para predecir — decisión Erika 2026-07-07). No necesita regresión de precio.
19. El pilot-first de Erika **funcionó como gobernanza**: $0 gastados, cero horas de rework
    de Silver invertidas en una hipótesis que el piloto mató en 20 minutos de cómputo.

---

## Experimento H10.3 — Vol-targeting sobre el campeón (familia H10, trial 1)

**Fecha:** 2026-07-07 · **Estado:** ❌ **NO PROMUEVE** (falla 2 de 4 criterios) — pero es
**el intento más cercano del proyecto** y deja una lección de diseño. **Pre-registro:**
`docs/DESIGN_H10_procesos_estocasticos.md` (commit `2e058e2`, ANTES de resultados).
σ_target=25% anual fijo, EWMA λ=0.94 sobre retornos del campeón (sin look-ahead,
warmup 20d), brazo A diario con-estado, DSR a n=30.

| @36bps | Campeón H6 | **Vol-target** | Criterio |
|---|---|---|---|
| Sharpe anual | 0.927 | **1.024** | ✅ supera |
| Max drawdown | −61.9% | **−39.8%** | ✅ mejor |
| Vol anual | 45.9% | 27.8% | (−40% de riesgo) |
| Fee drag anual | 32.2% | 19.1% | (menos churn) |
| PSR(0) | 0.976 | 0.988 | ✅ >0.95 |
| **DSR (n=30)** | — | **0.535** | ❌ <0.90 |
| Por año vs campeón | — | pierde 2021/23/24, gana 2022/25 | ❌ pierde 3/5 |

Diagnóstico Mincer-Zarnowitz (sin DSR): b=0.71, R²=0.057 — la vol ES pronosticable
(pendiente cercana a 1) pero ruidosa a granularidad diaria.

**Lectura honesta:** el overlay hizo EXACTAMENTE lo que la teoría promete — mismo motor,
40% menos riesgo, mejor Sharpe, la mitad de drawdown. Muere por (a) DSR: a n_trials=30
no podemos descartar suerte de selección con 4.5 años de datos; (b) el criterio de
robustez anual en retorno ABSOLUTO castiga estructuralmente a un des-riesgador: pierde
los años alcistas POR DISEÑO (expone ~70% en promedio). El criterio era el firmado y se
aplica tal cual — pero queda la lección para futuros overlays de riesgo:

**Dónde NO ir / lecciones (actualizado):**
20. **Vol-targeting no promueve como generador de alpha** bajo criterios de retorno
    absoluto anual. Su valor demostrado es de RIESGO (maxDD −40% vs −62%): candidato
    natural a **capa defensiva de producto** (decisión de producto, no de research —
    p.ej. proteger el capital live). Si se re-testea como overlay, pre-registrar
    robustez anual en SHARPE-por-año — pre-registro nuevo, trial nuevo; NO se aplica
    retroactivamente a este resultado.

**Post-veredicto (2026-07-07, decisiones de Erika — gobernanza registrada):**
(a) **Promoción a dos niveles** para trials futuros (enmienda pre-run 3 del DESIGN H10):
vara live intacta + shadow-bar (Sharpe>vara ∧ PSR>0.90 ∧ IC>0) con juez forward.
NO retroactiva. (b) **Vol-targeting a shadow como capa de RIESGO** por decisión de
producto (sin claim de alpha — este veredicto queda intacto); implementación con el
logging H10.4, PR propio.

---

## Experimento H10.1 — Carry y flujo: funding rates + taker imbalance (4 trials)

**Fecha:** 2026-07-07 · **Estado:** ❌ **FALSIFICADO 4/4 — falla también la shadow-bar.**
**Pre-registro:** DESIGN H10 §H10.1 (commit `2e058e2`) + enmienda 3 (dos varas, `29ace04`).
Datos: funding perps Binance (8h, 2021→2025-07) + taker buy volume horario → DuckDB de
research (`research/h10/h10_data.duckdb`, medallón intacto). Features: mom del campeón +
fund_now/fund_z90/fund_d7/taker_imb/taker_imb_z90 + dummies. Tubería H9 exacta, DSR n=30.

| Trial @36bps | IC (p) | R² OOS | Sharpe | PSR | DSR | años perdidos | live | shadow |
|---|---|---|---|---|---|---|---|---|
| Ridge_A diario | −0.011 (0.30) | −0.020 | −1.03 | 0.02 | 0.00 | 5/5 | 💀 | 💀 |
| LGBM_A diario | +0.004 (0.73) | −0.033 | −1.21 | 0.00 | 0.00 | 5/5 | 💀 | 💀 |
| Ridge_B semanal | −0.022 (0.44) | −0.065 | −0.06 | 0.46 | 0.01 | 5/5 | 💀 | 💀 |
| LGBM_B semanal | −0.008 (0.78) | −0.080 | −0.12 | 0.41 | 0.01 | 4/5 | 💀 | 💀 |

A 10bps tampoco (mejor: 0.26). **Conclusión:** el funding y el flujo agresor,
**agregados a frecuencia diaria/semanal y usados como features de regresión
direccional**, no aportan señal en este universo/era — la información "fresca" muere
igual que la de precio en cuanto se la baja a la cadencia en que Hermes puede operar.

**Dónde NO ir (actualizado):**
21. **Funding/taker como features direccionales a cadencia diaria+ = nada** (4 trials,
    ni la shadow-bar). Matiz honesto: el **carry puro de funding** (cobrar la prima
    yendo contra el crowding, sin predecir precio) es una estrategia DISTINTA no
    probada — requiere venue de futuros (cobrar funding exige posición perp) y su
    propio pre-registro. No confundir este cierre con esa puerta.

---

## Experimento H10.2 — Spreads estacionarios OU/cointegración (2 trials)

**Fecha:** 2026-07-07 · **Estado:** ❌ **FALSIFICADO 2/2.** **Pre-registro:** DESIGN H10
§H10.2 (`2e058e2`; params a priori: EG rolling 90d p<0.05, half-life ∈[2,30]d, z 2/0.5,
timeout 2×HL). 344 días con spreads "cointegrados" activos (22% del tiempo).

| Trial @36bps | Sharpe | PSR | DSR n30 | maxDD | Criterio | Veredicto |
|---|---|---|---|---|---|---|
| T-neutral (spread puro, fees dobles) | **−1.71** | 0.00 | 0.00 | −82% | Sharpe>0.5 ∧ PSR>0.95 | 💀 pierde LOS 5 años; a 10bps también (−1.40) |
| T-tilt (long-only ±10% sobre campeón) | **0.899** | 0.973 | 0.43 | −62% | mejorar al campeón (0.927) | 💀 lo EMPEORA; shadow-bar tampoco |

**Conclusión:** la reversión de spreads entre majors correlacionados **pierde dinero
incluso antes de fees serios**: cuando dos majors "cointegrados" se separan, no es una
dislocación temporal que revierte — es un **cambio de régimen** que continúa (SOL/AVAX
2021, etc.). El tilt apenas perturba al campeón y solo le resta.

**Dónde NO ir (actualizado):**
22. **Stat-arb de cointegración entre majors cripto de este universo/era = anti-señal.**
    Las divergencias son cambios de régimen, no dislocaciones. (Consistente con #14/#15:
    el eje relativo ya había fallado como momentum cross-sectional.)

---

## CIERRE DEL ARCO H10 (2026-07-07) — el programa del doctor, medido completo

**7 trials, 0 promociones a live, 0 a shadow-bar.** Con H9: **13 trials en un día,
todos falsificados** — el mapa dónde-no-ir cubre ya: dirección con precio (ML ×6 +
regresión), carry/flujo como features, stat-arb relativo, y vol-targeting como alpha.
Lo que QUEDA VIVO y por qué:
- **Noticias forward-only** (H10.4): único eje de información no medido — protocolo de
  logging con gate de 90 días, pendiente de implementación.
- **Vol-targeting en shadow como capa de RIESGO** (decisión de producto de Erika —
  su mérito de riesgo es real: −40% DD; su claim de alpha quedó falsificada).
- **Primas que requieren otro venue** (funding carry real, staking) — fuera del alcance
  actual (Bitso spot long-only); documentadas, no probadas.
- **La claim defensiva del campeón sigue siendo la única validada en holdout.** Todo el
  research de hoy la REFUERZA: nada de lo probado le gana ni de cerca a fees reales.

---

## ARCO H11 (abierto 2026-07-11) — clasificador binario diario, laboratorio cloud, MXN

**Redefinición de research de Erika (2026-07-11):** el modelo de todas las hipótesis
pasa a clasificador binario; target POR SÍMBOLO `y = 1 si ret 24h en MXN > +1%`; meta
dual F1 ≥ 0.60 OOS (split híbrido 80/20: K=5 sorteos por bloques mensuales purgados +
corte temporal puro — ambos deben cumplir) y ~1% diario neto MXN en backtest. Modo
"iterar hasta lograrlo" CON firewall: live intocado; promoción solo vía slice de
confirmación one-shot (último 15%, intocable) + shadow ≥45d + sign-off.
Metodología sense-first: dossier de variables con gate de Erika antes de entrenar.
Pre-registro completo: `docs/DESIGN_H11_daily_classifier.md`.

**Antecedentes en contra (honestidad):** Exp. 0 (LightGBM binario 7d) y H7 (logística
7d) falsificados. Esto es horizonte/moneda/universo NUEVOS, pero el arco cuenta TODOS
sus trials en `experiments/trials.jsonl` (bucket research) para el DSR.

**Infra:** laboratorio 100% cloud (bucket `hermes-research-*`, job `hermes-lab`,
imagen `lab:vN`); datos duales Binance (observar, cable local) / Bitso (medir, MXN);
budget real 4,900 MXN con alertas 50/80% en vez de ledgers (autonomía cloud total).

| Trial | Qué | Resultado | Veredicto |
|---|---|---|---|
| (pendiente) | baseline logística, conjunto sense-first | — | — |

### H11 — Gate D1 cerrado + primeros trials (2026-07-12)

**Gate D1 (Erika)**: conjunto v1 aprobado = ret_1d, abs_ret_1d (derivada del U-shape
del dossier), btc_ret_1d, rv_20d, hl_range_z30, hurst_100d (a prueba). Fuera:
ewma_vol_20 (canary + redundancia 0.914 con rv_20d), vol_z30 (corr 0.822 con
hl_range_z30), rel_ret_5d/breadth/dow/usdmxn_ret_5d/quincena (sin señal — la
quincena salió CONTRARIA a la hipótesis de nómina). Puente v2 con FX del venue:
9/9 libros TRANSFIEREN (BTC 7.1bps; el FIX de FRED inflaba la regla de medición).

| Trial | Qué | Resultado | Veredicto |
|---|---|---|---|
| baseline-logistic | logística v1, umbral 0.5 | F1 0.094±0.025 / 0.048 temporal — artefacto de umbral (clase 34% casi nunca supera p>0.5). TP3 pierde MENOS que base (−0.06 vs −0.14%/día) | ❌ config, no señal |
| logistic-balanced | + class_weight=balanced | F1 0.440±0.022 / 0.405 temporal · precision 0.408 vs base rate ~0.34 (+7pp lift REAL) · backtest −0.26%/día: turnover 1.24/día × 46bps ≈ −0.57%/día de fricción | 🟡 señal débil; el turnover es el asesino |

**Aprendizaje del día**: (1) hay señal (lift de precisión consistente con el dossier);
(2) F1 0.60 en ambas validaciones sigue LEJOS (mejor: 0.44 < naive 0.51); (3) ninguna
estrategia diaria sobrevive turnover ~1.2/día a 46bps — los siguientes trials van a
umbral alto/menos trades y LightGBM (interacciones + U-shape). n_trials acumulado: 2.

### H11 — Tanda 2: umbral alto, LightGBM, motor v2 (suavizado + benchmark) (2026-07-12)

Motor v2 del backtest (`smooth_alpha` = ejecución suavizada w_exec = α·target +
(1−α)·w_prev; benchmark buy&hold equal-weight del mismo periodo en cada corrida —
el control alpha-vs-beta que faltaba). `TrialSpec.strategy` pasa extras al motor
vía spec JSON. Fee real verificado en el adapter live: maker 0.30% vs taker 0.36%
(libros USDT/USD; los /MXN cobran DOBLE y el live ya los evita) → el fee NO es la
palanca; el turnover sí.

| Trial | Qué | Resultado | Veredicto |
|---|---|---|---|
| thr060 | balanced, umbral 0.60 | F1 0.134/0.077 (recall 4%) · precision 0.427 · bruto ≈ −0.03%/día | ❌ la convicción alta NO tiene edge bruto |
| thr065 | balanced, umbral 0.65 | precision 0.523 (¡>50%!) pero bruto ≈ 0 · TP3 −0.002%/día (breakeven) | ❌ ídem — precisión ≠ retorno |
| lightgbm-base | LGBM is_unbalance, 0.5 | F1 0.432±0.024 / 0.441 (mejor temporal hasta hoy) · bruto +0.26%/día · neto −0.39 (turnover 1.39) | 🟡 no rescata; mismo techo |
| logistic-sm033 | balanced + α=0.33 | **neto +0.11%/día** · turnover 0.39 · Sharpe 0.55 | 🟡 primera config positiva |
| logistic-sm015 | balanced + α=0.15 | **neto +0.164%/día, +39% total, Sharpe 0.85, DSR 0.32** · turnover 0.18 · **exceso vs B&H −0.076%/día** | 🟡 mejor config del arco; NO le gana al mercado |
| lgbm-sm033 | LGBM + α=0.33 | neto +0.02%/día · exceso −0.22 | ❌ |

**Aprendizajes de la tanda (n_trials: 8):**
1. **El benchmark responde la pregunta central: B&H equal-weight hizo +0.239%/día en
   el holdout → TODO el "bruto positivo" de los modelos era mayormente beta.** Ningún
   trial tiene exceso positivo sobre simplemente sostener la canasta (mejor: −0.076).
2. El edge de clasificación (lift +7pp precision, +18pp en p>0.65) NO se convierte en
   retorno: la cola de alta convicción tiene bruto ~0 — la asimetría de los errores se
   come la precisión.
3. Suavizar la ejecución funciona exactamente como se hipotetizó (turnover 1.24→0.18)
   y produce las primeras configs netas positivas — pero cuando α→0 la estrategia
   CONVERGE al benchmark sin superarlo: la señal diaria no agrega encima del mercado.
4. **TP-3% (task #10) en configs ganadoras: DESTRUYE** (+0.164 → −0.086%/día). En un
   holdout tendencial, capear la cola derecha amputa los días que pagan todo. Evidencia
   acumulada: el TP solo "ayudó" reduciendo pérdidas de configs perdedoras.
5. Meta dual a hoy: F1 mejor 0.44 vs 0.60 (naive 0.51) · neto mejor +0.164%/día vs ~1%.
   La familia actual (clasificador diario absoluto >1%) muestra techo estructural.

### H11 — ENMIENDA v2: pivote a target relativo + entierro del TP-3% (2026-07-12)

**Decisión de Erika tras ping-pong** (opción A de la bifurcación): label v2
`rel_median` (¿le gana el símbolo a la mediana de la canasta mañana? — 50/50 por
construcción, el beta se cancela) + metas renegociadas: **accuracy > 0.55 en ambas
validaciones + profit factor ≥ 1.5 + exceso vs B&H > 0** (reemplazan F1 0.60 y el
~1%/día — este último reconocido como no realista: 1%/día = +3,678% anual).
Enmienda completa: `DESIGN_H11_daily_classifier.md` §9. n_trials continúa (no se
resetea). Mini-D1 sense-first contra el label nuevo ANTES de entrenar (gate Erika).

**TP-3% (task #10) — VEREDICTO FINAL: ❌ ENTERRADO.** Evidencia (8 trials, variante
siempre-corrida): destruye toda config ganadora (+0.164 → −0.086%/día en la mejor)
porque amputa la cola derecha que paga la estrategia; solo "ayudó" reduciendo
pérdidas de configs ya perdedoras (trials 1, 3, 4). Contradice además la meta de
asimetría ("ganancias >> pérdidas" exige colas derechas LARGAS). El watchdog upside
NO se construye. Reemplazo pre-registrado: variante **stop-loss −3%** (corta la cola
izquierda — el lado correcto de la distribución para esa meta).

### H11 — Tanda 3: primeros trials del label relativo (gate v2 aprobado) (2026-07-12)

Gate del dossier v2 aprobado por Erika ("VAMOS!") → FEATURE_SET_V2 congelado
(ret_2d, abs_ret_1d, btc_ret_1d, rv_20d, hl_range). Trials con label `rel_median`,
suavizado desde el arranque (lección de la tanda 2), SL-3% siempre como variante.

| Trial | Qué | Resultado | Veredicto |
|---|---|---|---|
| rel-logistic-sm015 | logística, α=0.15, k=5 | acc 0.5129±0.004 / 0.5128 · AUC 0.522 · **+0.169%/día, +59.5% total, Sharpe 1.25, maxDD −39%, DSR 0.38** (todos, récord del arco) · PF 1.21 · exceso −0.070 | 🟡 mejor config del arco; no cumple metas |
| rel-logistic-sm033 | ídem α=0.33 | +0.093%/día · exceso −0.146 | ❌ (α=0.15 domina) |
| rel-lightgbm-sm015 | LGBM, α=0.15 | acc 0.507/0.516 · +0.152%/día · exceso −0.087 | ❌ no supera a la logística |
| rel-log-sm015-k10 | tilt amplio k=10 | +0.177%/día · exceso −0.062 · PF 1.19 | 🟡 mejora marginal; no voltea el exceso |

**Aprendizajes de la tanda (n_trials: 12):**
1. **La señal relativa es REAL pero diminuta**: acc 51.3% (naive 50%), AUC 0.52,
   estable en ambas validaciones y ambos modelos. +1.3pp sobre la moneda.
2. **El SL-3% muere igual que el TP-3%**: destruye toda config (+0.169 → −0.022;
   PF cae bajo 1). A vol diaria de cripto (~3-5%), un toque de −3% intradía es RUIDO,
   no señal de salida: vende en el dip días que cierran arriba. **Conclusión de par:
   NINGÚN mecanismo de salida intradía a ±3% sobrevive en este universo — el nivel
   está dentro de la banda de ruido.** (dónde-no-ir nuevo)
3. **El cálculo decisivo**: exceso neto −0.062 con costo ~0.053%/día → el exceso
   BRUTO del tilt sobre la canasta EW es ≈ 0. La acc de 51.3% se concentra en
   empates cerca de la mediana (aciertos sin magnitud); el top-k no extrae valor
   económico de ella. Concentrar (k=5) o ampliar (k=10) no cambia el signo.
4. Metas v2 a hoy: acc 0.513 vs 0.55 · PF 1.21 vs 1.5 · exceso −0.062 vs >0.
   Sí mejoró TODO vs la familia absoluta (Sharpe 1.25 vs 0.85; maxDD −39 vs −57;
   DSR 0.38 vs 0.32) — dirección correcta, magnitud insuficiente.

### H11 — Tanda 4: label de extremos (§10) + barrido de formación larga (2026-07-12)

Enmienda §10 (idea Erika: top-k como target + purga de banda de ruido): label
`extremes_k5` — top-5 vs bottom-5 del día, banda media fuera del training, 50/50 por
construcción. Regla anti-leakage explícita: el backtest puntúa TODAS las filas con
features válidas. Métrica nueva: precision@5 (naive ≈ 24%). Salidas intradía ±3%
retiradas del default (TP y SL enterrados).

| Trial | Qué | Resultado | Veredicto |
|---|---|---|---|
| ext5-logistic-sm015 | logística extremos, α=0.15 | acc 0.520±0.008/0.517 · AUC 0.536 (récord) · **+0.196%/día, +73.8% total, Sharpe 1.41, maxDD −38.6% (récords del arco)** · PF 1.24 · **exceso −0.043** · precision@5 0.230 ≈ naive 0.238 | 🟡 mejor config del arco; exceso aún <0 |
| ext5-lightgbm-sm015 | LGBM extremos | acc 0.517/0.508 · +0.093%/día · exceso −0.146 | ❌ LGBM pierde vs logística por 3ª vez |

**Barrido de formación larga (D1, sin costo de trial)**: ret_21d IC +0.0247 (p=0.023)
pero deciles NO-monótonos (50.3/54.4/49.6 — joroba en D5); ret_63d IC +0.0294 (p=0.008)
con deciles PLANOS (49.5/50.5/49.3 — correlación sin patrón rankeable). Sin redundancia
con el set v2. Veredicto: ⚠️ NO es la palanca — IC nominal sin estructura económica.
Patrón de régimen consistente en TODO el cluster momentum: IC positivo en vol baja/media,
~0 o negativo en vol alta.

**Aprendizajes de la tanda (n_trials: 14):**
1. **La progresión por label es monótona y converge SIN cruzar**: exceso −0.13 (absoluto)
   → −0.062 (mediana) → **−0.043 (extremos)**. Cada refinamiento acerca al benchmark;
   ninguno lo supera. Con costo ~4.8bps/día, el exceso BRUTO de extremos ≈ 0 otra vez.
2. **precision@5 ≈ naive**: el modelo NO identifica el top-5 real mejor que el azar,
   aunque clasifica extremos a 52% y su backtest es el mejor del arco — la mejora vino
   de mejor *tilt* de cartera (low-vol + momentum suave), no de selección de ganadores.
3. El barrido sense-first del espacio relativo diario está COMPLETO: momentum corto
   (débil+), formación larga (débil/plano), vol (limpia−, la mejor), lead-lag BTC
   (débil+), calendario/FX (muertos). No quedan esquinas teóricas obvias sin medir
   a esta granularidad.
4. Metas: acc 0.520 vs 0.55 · PF 1.24 vs 1.5 · exceso −0.043 vs >0. Todo mejoró de
   nuevo; nada cruzó.

### ARCO H11 — CERRADO CON VEREDICTO (2026-07-12) → abre ARCO H12

**VEREDICTO (14 trials, 3 familias de label, 2 modelos): a horizonte de 1 DÍA no hay
alpha de selección cross-seccional sobre la canasta equal-weight en este corpus.**
El exceso convergió monótonamente (−0.13 → −0.062 → −0.043) sin cruzar 0; el exceso
bruto fue ≈ 0 en TODAS las familias; precision@5 ≈ azar. La señal de clasificación es
real (acc 52%, AUC 0.536) pero vive en aciertos sin magnitud. Mejor config del arco:
ext5-logistic-sm015 (+0.196%/día, Sharpe 1.41, DSR 0.363) — un TILT sano (low-vol +
momentum suave + ejecución lenta), no un selector de ganadores. **El slice de
confirmación queda VIRGEN** (ningún candidato pasó las metas — no se quema).
Enterrados con evidencia: TP+3%, SL−3% (±3% intradía = ruido), formación larga a 1d
(deciles planos), breadth day-constant (artefacto), quincena, hurst (×2).
Activos que deja el arco: laboratorio cloud completo (bucket+job+imagen v11),
motor de backtest con control B&H y cadencia, metodología dossier sense-first,
datos duales Binance/Bitso con puente validado. Gasto: ~$5 de $290 (1.7%).

**ARCO H12 ABIERTO** (directiva Erika: "De una. No me rindo"): mismo target ganador
(extremos relativos) a horizontes H ∈ {3, 7, 14} — grilla CERRADA pre-registrada.
⛰️ REGLA EN PIEDRA (§3 del pre-registro): cadencia de rebalanceo (backtest Y
producción) = horizonte del label entrenado, sin excepciones. Purga/embargo escalan
con H. Mini-D1 por horizonte con gate de Erika antes de entrenar.
Pre-registro completo: `docs/DESIGN_H12_horizon_sweep.md`.

### H12 — Tanda 1: barrido de horizontes (trials 15-17) (2026-07-12)

Gate de sets cerrado (§8). Logística por horizonte, label extremes_k5, top-5, sin
suavizado, cadencia = H (regla en piedra §3), purga/embargo = H. n_trials: 17.

| H | acc bloques/temporal | p@5 | %/periodo | bench | **EXCESO/periodo** | PF | Sharpe | periodos |
|---|---|---|---|---|---|---|---|---|
| 3d | 0.521/0.535 | 0.251 | +0.450 | +0.748 | −0.298 | 1.34 | 1.18 | 115 |
| 7d | 0.525/0.533 | 0.237 | +0.305 | +1.616 | −1.311 | 1.13 | 0.31 | 49 |
| **14d** | **0.525/0.553** | 0.265 | **+5.597** | +3.568 | **+2.029** 🎯 | **3.26** | 1.34 | **25** ⚠️ |

**H=14 es el PRIMER exceso positivo del proyecto** (+171% total vs +140% del B&H;
PF 3.26 ≥ meta 1.5; acc temporal 0.553 ≥ 0.55). PERO honestidad completa:
1. **25 periodos** — muestra diminuta; 2-3 bloques afortunados pueden explicar todo.
   DSR 0.17 (castigado por n_trials=17 y n chico). La meta acc falla en BLOQUES
   (0.525 < 0.55) → metas NO cumplidas formalmente (exigen ambas validaciones).
2. **No-monotonicidad sospechosa**: H3 −0.30, H7 −1.31 (el peor), H14 +2.03. Si el
   patrón fuera señal pura se esperaría transición suave. Alerta de ruido.
3. La grilla t0+k·14 usa UNA fase — la robustez a las 14 fases posibles (offsets
   0..13, mismo modelo entrenado, sin re-elegir nada) es el siguiente test OBLIGADO
   antes de cualquier entusiasmo. Se reporta media±rango de las 14 fases.

**Siguiente**: (a) test de robustez de fase para H=14 (diagnóstico del mismo trial,
no cuenta como trial nuevo — no se selecciona nada con él); (b) distribución por
bloque (¿cuántos de los 25 aportan el exceso?); (c) si sobrevive → fase NN §7 sobre
H=14 y considerar grilla extendida {21, 28} vía nueva enmienda con gate.

### H12 — Phase check de H=14 (diagnóstico, 2026-07-12): EL EXCESO SOBREVIVE

Mismo modelo del trial 17 re-evaluado en las 14 fases de la grilla (offsets 0-13;
NO cuenta como trial — no se seleccionó nada): **13/14 fases con exceso POSITIVO**,
media **+1.45%/periodo**, rango [−0.46, +2.63], σ 0.87. El +2.03 del offset 0 no era
suerte de calendario. Matices honestos: (1) un bloque de **+97.9%** (rally alt de 2
semanas en el holdout) carga gran parte del total — sin él, el neto medio del offset
0 cae de 5.60 a 1.75%/periodo (aún > 0); (2) 14/25 bloques positivos (56%); (3) todas
las fases comparten el MISMO año de mercado — la robustez es a la fase, no al régimen.
El slice de confirmación (otro régimen) sigue virgen y será el juez final.
**Siguiente (sin gate, protocolo §9): fase NN §7 sobre H=14 (máx 2 configs) y
enmienda de grilla {21, 28} pre-registrada.** Meta formal aún NO cumplida (acc
bloques 0.525 < 0.55) — el firewall no se dispara todavía.

### H12 — Tanda 2: grilla extendida {21, 28} (trials 18-19 + phase checks) (2026-07-12)

Enmienda §10. Sets por regla lookback ≥ H desde dossiers _h21/_h28 (el IC de ret_63d
siguió creciendo: +0.094 a 21d, +0.104 a 28d; hurst revivió débil en U — fuera).
H=28 quedó en UNA variable: ret_63d (momentum trimestral puro — superficie mínima
de overfit). Métrica primaria = media del phase check (§10; el holdout da 13-17
periodos por fase a estos H).

| H | acc blq/temp | exceso medio (fases) | positivas | equiv. %/día | PF (off0) | top1 bloque |
|---|---|---|---|---|---|---|
| 14 | 0.525/0.553 | +1.45 | 13/14 | +0.10 | 3.26 | +98% |
| 21 | 0.518/0.498 | +2.44 | 17/21 | +0.12 | 2.06 | +169% |
| 28 | 0.526/0.527 | **+5.02** | **26/28** | **+0.18** | 3.31 | +174% |

**Aprendizajes (n_trials: 19):** (1) el exceso crece MONÓTONO con H en toda la grilla
medible — la fisiología es momentum cross-seccional de formación trimestral cosechado
a cadencia mensual; (2) la acc de clasificación NO acompaña (H21 temporal 0.498 —
¡moneda! — con economía positiva): el dinero está en la MAGNITUD concentrada de los
extremos que el ranking captura, no en la tasa de acierto → la meta acc>0.55 mide la
dimensión equivocada para esta familia (tema para Erika); (3) los bloques monstruo
(+98/+169/+174%) dominan los totales — estrategia de cola derecha: pierde chico
seguido, gana enorme rara vez (PF>2-3 aun así); (4) tope de data: H>28 dejaría <10
bloques por fase en el holdout — la grilla NO se extiende más; el juez de régimen
sigue siendo el slice de confirmación (virgen). Siguiente: fase NN §7 sobre H=28/14
y decisión de metas con Erika.

### H12 — Metas v3 evaluadas (2026-07-12): H=28 pasa 3/4; M4 falla por 0.0015

| Meta | H=28 | Veredicto |
|---|---|---|
| M1 exceso phase-mean > 0 en {14,21,28} | +1.45 / +2.44 / +5.02 | ✅ |
| M2 PF phase-mean ≥ 1.5 | 3.14 | ✅ |
| M3 exceso > 0 SIN el mejor bloque | **+0.80/periodo, 21/28 fases** | ✅ (¡sobrevive al anti-episodio!) |
| M4 AUC > 0.52 en ambas | temporal 0.5236 ✅ · **bloques 0.5185** | ❌ por 0.0015 |

Notas: H21 FALLA M3 (−0.40 sin top1 — su exceso sí era episodio); H14 pasa M3 apenas
(+0.33, 9/14). H=28 es el único robusto de punta a punta en lo económico. M4 falla en
los sorteos por bloques (incluyen 2021-22 bear, donde el momentum se apaga — consistente
con el patrón de régimen del dossier). **Regla del proyecto: la meta NO se ablanda
después de ver el resultado** (eso sería verdict-shopping) → el candidato NO entra al
firewall todavía. Camino pre-registrado que sigue: fase NN §7 sobre H=28 (¿un modelo
con más información puede subir el piso de ranking sin perder M1-M3?). n_trials=19.

**Directiva Erika (2026-07-12): ext5-h28 NO se descarta por M4** — "no pasó por un
pelito de rana calva; hasta ahora es nuestro mejor candidato". Estatus formal:
**CANDIDATO CAMPEÓN DEL ARCO** (M1-M3 ✅, PF 3.14, exceso anti-episodio +0.80).
Camino honesto acordado, sin ablandar la vara: (1) **shadow pre-firewall a cadencia
28d arranca lo antes posible** (papel, cero riesgo, no consume el slice) — cada
periodo suma un punto de evidencia fresca OOS que puede zanjar M4 legítimamente;
(2) la fase NN §7 corre como CHALLENGER del campeón; (3) el one-shot del slice
sigue reservado para cuando la evidencia acumulada lo justifique + sign-off.

### H12 — Shadow pre-firewall del campeón ARRANCADO (2026-07-12, §12 del pre-registro)

Modelo congelado `models/h12-ext5-h28.json` (sha 0be0129e7e5f): receta del spec
re-entrenada sobre TODA la iteración (16,489 filas, 2021-03-05 → 2025-09-10; el
slice de confirmación jamás entrena). Emisión diaria vía Cloud Scheduler
(`hermes-shadow-h12-emit`, 00:20 UTC) sobre el universo Bitso MXN operable
(10 libros); **rebalanceo solo en la grilla ancla+k·28**. Ledger:
`shadow/h12-ext5-h28/days/` · reporte vivo: `reports/shadow_h12_ext5_h28.md`.

**Incidente documentado**: la emisión inaugural corrió a las ~19h UTC y la barra
del día EN CURSO (20 velas ≥ umbral 20 de `_daily_bars`) pasó como día completo —
decisión con día parcial. Fix: filtro por fecha (`complete_days`, solo barras
< hoy UTC) + test; el ledger (1 entrada, minutos de vida, defecto conocido) se
RESETEÓ y se re-ancló con el último día completo. Único reset permitido: día 0,
antes de acumular evidencia.

**Hallazgo que corrige la narrativa — el campeón NO es momentum, es REVERSIÓN
débil en los extremos**: el freeze expuso coef(ret_63d) = −0.067, y la
verificación read-only del modelo EVALUADO (temporal holdout) da −0.082 (todos
los block draws negativos: −0.016…−0.076). La regla que pasó M1-M3 compra los
símbolos MÁS GOLPEADOS del trimestre (bottom ret_63d), no los ganadores. El IC
+0.104 del dossier era sobre TODAS las filas (momentum en el rango medio); en el
contraste de extremos top-5/bottom-5 domina la reversión — ambas cosas son
ciertas a la vez. Nada cambia en la evidencia (misma regla evaluada, mismo
freeze, y el top-5 de un modelo monótono de 1 variable es invariante a la
magnitud del coef); cambia la ETIQUETA económica: contrarian trimestral con
tilt inverse-vol. n_trials sigue en 19 (freeze/shadow no son trials).

### H12 — Fase NN, config 1 (GRU secuencias): trial `nn1-gru-h28-20260712` (n_trials=20)

Pre-registro §7.1 (hiperparámetros congelados antes de correr). GRU(32) sobre
secuencias 84d de canales estacionarios del OHLCV, extremes_k5 H=28, mismo split
y mismo motor de backtest que el campeón.

| Métrica (holdout temporal 2024-09→2025-09) | GRU NN-1 | Campeón ext5-h28 |
|---|---|---|
| Exceso fase-media (28 offsets) | **+7.61%/periodo (28/28 fases +)** | +5.02 (26/28) |
| Anti-episodio (sin top1) | **+3.53 (27/28)** | +0.80 (21/28) |
| PF fase-media | **4.13** | 3.14 |
| AUC temporal | **0.5995** | 0.5236 |
| AUC bloques (K=5 sorteos) | **0.5052 ❌** (rango 0.45–0.55) | 0.5185 ❌ (por 0.0015) |

Lectura honesta: el GRU le gana al campeón en TODO lo económico del holdout —
supera el baseline en el año reciente por margen amplio — pero su ranking en los
sorteos por bloques es MONEDA AL AIRE con varianza brutal (draws en 0.45 = ranking
activamente equivocado en regímenes viejos; pred_rate 0.12–0.53 entre draws =
calibración inestable del umbral). M1-M3 como challenger: ✅✅✅. M4: ❌ en bloques
(peor que el campeón en robustez, mejor en el régimen reciente). Caveats: 13
periodos en offset0, DSR 0.077 (n=20 trials, pocas obs), maxDD −45.8%, y la
expectativa pre-registrada de que el holdout fue año excepcional aplica DOBLE a
un modelo de más capacidad. Veredicto: **challenger legítimo, mismo talón de
Aquiles (M4-bloques) que el campeón pero amplificado en ambas direcciones** — la
adjudicación honesta es forward: candidato natural a segundo stream del shadow
(decisión de infra para la próxima sesión). Config NN-2 (TTM) pendiente, §7.2
congelará sus hiperparámetros antes de correr.

### H12 — GRU entra al shadow como segundo stream (2026-07-12, §12.1)

Artefacto congelado `models/h12-gru-h28.json` (sha 4a52a1d4e870; 16,184 filas,
2021-04-03 → 2025-09-10, receta §7.1, state_dict JSON sin pickle). Primera
emisión multi-stream (misma ancla 2026-07-11, mismo universo):
- campeón `h12-ext5-h28`: BCH/AVAX/MANA/ETH/LTC (contrarian trimestral)
- challenger `h12-gru-h28`: BAT/TRX/XRP/SOL/BTC (secuencias)
**Portafolios 100% disjuntos** — se repartieron el universo en visiones opuestas;
el forward va a separar señal de ruido con contraste máximo. Selection effect
declarado: 2 streams compiten (§12.1); la promoción eventual lo descuenta.

### H12 — window_check §13 (2026-07-12): la economía multi-régimen INVIERTE la jerarquía

Protocolo pre-registrado (vara fijada ANTES de correr): 40 ventanas de 28d no
solapadas (2021-04 → 2025-09), re-entreno por ventana con purga/embargo 28d,
mismas ventanas para ambos, costo de entrada completo en ambos lados.

| | campeón ext5-h28 | GRU nn1 |
|---|---|---|
| Exceso mediano/ventana | **−1.24%** | **+1.99%** |
| Exceso medio | −2.21% | +1.22% |
| % ventanas positivas | 35% | 62.5% |
| 2021 | −8.04 | −1.85 |
| 2022 | −1.83 | +0.31 |
| 2023 | −0.85 | +0.46 |
| 2024 | −1.58 | +2.52 |
| 2025 | +0.81 | +4.98 |
| Vara §13 (mediana>0 · ≥55%+ · sin año <−1%) | ❌❌❌ **NO PASA** | ✅✅❌ **NO PASA** (2021: −1.85) |

Lectura honesta:
1. **El "campeón" era un artefacto del régimen reciente.** Su exceso +5.02/periodo
   vivía SOLO en el año del holdout; en el resto de la historia pierde contra la
   canasta en TODOS los años (2021: −8%/periodo). El M4-bloques que falló "por un
   pelito" era el canario — window_check confirma la contraparte económica.
2. **El GRU se sostiene donde el campeón se cae**: positivo en 4/5 años, mejora
   monótona 2021→2025, mediana +1.99. Falla la vara SOLO por 2021 (−1.85 < −1.0).
   La varianza de AUC entre draws (0.45-0.55) convive con economía positiva —
   otra vez: el dinero está en la magnitud, no en la tasa de acierto.
3. **Nadie pasa la vara pre-registrada** → nadie gana sello; la vara NO se
   ablanda. Pero la jerarquía del arco se invierte: el GRU es el candidato más
   robusto entre regímenes y el "campeón" NO debe acercarse al firewall con esta
   evidencia. Caveats: alta varianza por ventana (rango ±35%), ~8 ventanas/año,
   re-entreno ve futuro relativo a su ventana (robustez de señal, no deploy —
   el shadow multi-stream sigue siendo el juez). n_trials sin cambio (20).
