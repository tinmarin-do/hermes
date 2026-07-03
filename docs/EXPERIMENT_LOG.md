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
