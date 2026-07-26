# DESIGN H14 — Prima de rebalanceo ("cosecha del vaivén") a escala de todo el mercado

**Pre-registro del arco de research. Commiteado ANTES de cualquier corrida (regla de la casa).**
Aprobado por Erika 2026-07-26 (plan mode). El arco H13 (gruls-ivol: shadow, firewall, plomería)
sigue intacto y NO compite con este hilo — mismo bloque de reglas cloud y mismo presupuesto.

> **v2 desde el nacimiento**: el borrador v1 pasó por dos críticos adversariales independientes
> (metodológico + cuantitativo con verificación Monte Carlo) ANTES de aprobarse. Encontraron
> 3 defectos invalidantes que esta versión corrige; el registro completo está en §11 y forma
> parte del expediente de la hipótesis.

## §1 Identidad, fenómeno y mecanismo

Observación de Erika (conversación 2026-07-25/26): "diario gano cierta cantidad y al día
siguiente ya bajó mi portafolio" — quiere capturar el vaivén DIARIO del mercado, con universo
ampliado a TODO el mercado (no la whitelist de 6).

Mecanismo candidato: **mezcla fija (fixed-mix)** símbolo-vs-su-propio-cash re-normalizada a
diario. Vende mecánicamente cada subida y compra cada bajada, sin predecir nada (*rebalancing
premium / volatility harvesting*; Fernholz & Shay 1982; Dempster, Evstigneev & Schenk-Hoppé
2007). **Desambiguación**: esto NO es "cosechar beta" (DIAGNOSTIC_EARNINGS §4.3 = tomar
dirección de la canasta); aquí no hay dirección — se cosecha la oscilación.

### §1.1 La teoría, puesta derecha (corrección central de la crítica v1→v2)

Hay DOS benchmarks y no son intercambiables:

- **γ\* clásico** = exceso del fixmix sobre el *promedio ponderado de crecimientos geométricos
  individuales* = ½·w(1−w)·σ² por periodo. Positivo SIEMPRE, incluso bajo random walk
  (teorema de Dempster et al.). Pero ese benchmark NO es "no hacer nada" — es contabilidad.
- **Premio vs buy-and-hold** (la experiencia real de Erika: rebalancear vs quedarse quieta).
  Verificado por Monte Carlo en la crítica adversarial: **bajo random walk puro es ≈0 a corto
  plazo y NEGATIVO a largo** (el fixmix re-alimenta un activo con drag de varianza; el B&H
  conserva su piso de cash). Chambers & Zdanowicz (2014): *cualquier valor esperado extra del
  rebalanceo emana de mean-reversion, no de la reducción de varianza*.

**Condición necesaria de toda la H**: anti-persistencia medible y vigente (VR<1) en el
universo ejecutable. Sin ella no hay premio contra no-hacer-nada — solo aritmética bonita.

### §1.2 Enunciado

*En el segmento ejecutable de los perpetuos USDT-M de Binance, los retornos diarios exhiben
anti-persistencia estadísticamente distinguible y vigente (H-A, H-C); y condicional a ello,
un fixmix diario símbolo-vs-cash genera crecimiento compuesto neto superior a no rebalancear,
cargando fricciones simétricamente (H-B, trial contado en F3).*

Marco: es una apuesta **Kelly-coherente** (maximiza crecimiento log, el maximand ya adoptado
por la casa) — nunca se reporta como "alpha en valor esperado". Nota honesta: a Kelly
fraccional 0.10 el beneficio se encoge proporcionalmente; el marco es legítimo, no mágico.

### §1.3 Prior honesto pre-registrado: **~15%** de que H-A y H-C sobrevivan en el estrato
ejecutable. Derivación en §7 (aritmética ex-ante) y §3 (precedentes en contra).

## §2 Particiones y contaminación

- **Iteración**: 2021-01-01 → 2025-06-30. **Confirmación**: 2025-07-01 → 2026-06-30.
- F2a computa estadísticos de estructura sobre TODO el rango (H-C exige la ventana reciente)
  → la partición de confirmación queda TOCADA por estadísticos descriptivos. **Caveat
  §2.1-style (heredado de DESIGN_H13 §2.1)**: cualquier pase histórico de F3 se reporta
  siempre como "pase en datos estructuralmente examinados", jamás como evidencia virgen.
- **Juez primario de H14 = shadow forward** (evidencia 100% virgen), igual que gruls-ivol.
  Un pase de F3 solo compra el derecho al shadow; jamás abre dinero por sí solo.
- **Fecha de corte fija**: datos hasta **2026-06-30** (zips mensuales completos), pase lo que
  pase con el momento de la descarga.

## §3 Precedentes (citados ANTES de correr — "no se re-mide sin mostrar la evidencia")

En contra:
1. **Zaremba, Bilgin, Long, Mercik & Szczygielski (2021, IRFA; >3,600 monedas)**: el reversal
   diario cripto es un efecto de ILIQUIDEZ — el segmento líquido (donde ejecutamos) muestra
   MOMENTUM diario. La predicción direccional más peligrosa para H14; el mapa liquidez×vol de
   F2a (§6) la testea de frente.
2. **Nuestros propios datos** (`trend_study` h=1, 29 símbolos): persistencia pooled por año
   2021→2026: 0.468, 0.453, 0.461, 0.487, 0.492, **0.518** — el vaivén se apaga y 2026 cruzó
   a persistencia. Por eso existe H-C.
3. **Autopsia del watchdog (H13-§14, 2026-07-25)** y **±3% de H11 (§10.3)**: intervenir
   posiciones a diario amputó dos veces la cola derecha. El fixmix institucionaliza el mismo
   gesto (vender ganadores a diario). Diferencia argumentada: aquellos eran overlays de salida
   SOBRE una tesis de momentum (peleaban contra su propio libro); H14 es la tesis opuesta
   completa, sin señal ni umbral. Aun así, esta familia de evidencia baja el prior.
4. **H11 (veredicto de cierre, 14 trials)**: "a horizonte de 1 DÍA no hay alpha de selección
   cross-seccional en este corpus". H14 no es selección (no predice, no rankea) — pero opera a
   la misma frecuencia donde la señal predictiva ya murió.
5. **H10.2**: la reversión OU/cointegración entre majors PIERDE dinero. Misma familia
   económica (mean-reversion), mecanismo distinto.
6. **Espirales de muerte**: el fixmix DOBLA la apuesta en colapsos. LUNA a −20%/día × 30 días:
   sleeve fixmix ×0.042 vs ×0.50 del B&H 50/50 (el B&H conserva el piso de cash; el fixmix lo
   gotea al agonizante). Matiz de la crítica: en un colapso de UNA vela ambos pierden igual —
   el daño depende del número de rebalanceos durante la caída; el espécimen §6 usa el path real.

A favor:
- El vaivén pooled 2021-23 fue real (persistencia 0.45-0.46) y el candidato vivo del overlay
  (campeón momentum) es él mismo reversión débil en los extremos (EXPERIMENT_LOG H8).
- La teoría del premio es sólida EN SU BENCHMARK (γ\* clásico); la pregunta empírica honesta
  es si existe la mean-reversion que lo convierte en premio vs B&H.

## §4 Fases y conteo de trials (frontera DSR explícita)

| Fase | Contenido | Estatus DSR |
|---|---|---|
| **F0** | Este DESIGN commiteado + entrada de pre-registro en EXPERIMENT_LOG | — |
| **F1** | Corpus anti-supervivencia (Binance Vision): klines 1d + funding, ~800 perps USDT-M históricos, deslistados incluidos | — |
| **F2a** | EDA de ESTRUCTURA pura: VR/ρ₁/persistencia con IC robustos, gemelos, mapa liquidez×vol, espécimen cartera propia. **Sin P&L, sin costos, sin veredicto económico.** Gates: H-A, H-C | **Descriptivo, NO cuenta** (mismo estatus que trend_study: estadísticos, no estrategias) |
| **F3** (condicional a que F2a pase) | UN config costeado: w=½, **f=1d exclusivamente**, fixmix vs B&H con fricciones simétricas. Gates H-B(i)/(ii). Requiere: pre-registro propio (enmienda §12+), vara aprobada por Erika, y enmienda ⛰️ aprobada — TODO antes de correr | **1 trial contado (n 29→30)** |

**Compromisos anti forking-path (escritos hoy, inamovibles):**
1. Cualquier F3 usa **f=1d** (la frecuencia titular). Evaluar económicamente cualquier otra
   frecuencia = enmienda pre-registrada nueva y cuenta su propio trial. La grilla VR(f) de
   F2a es diagnóstico de estructura, jamás menú de configs.
2. **La línea spot es referencia y no resucita nada**: H-B se falsifica con fricciones de
   perps USDT-M exclusivamente. "En spot sobreviviría" exigiría H nueva pre-registrada.
3. **Numerario**: veredicto primario en USDT (dominio nativo del mecanismo: fees y funding se
   cobran en USDT); MXN reportado siempre (regla de la casa). Si el SIGNO del veredicto
   difiere entre numerarios → "no pasa" automático.
4. **Un pase histórico de F3 no abre dinero**: habilita únicamente shadow forward, luego el
   firewall completo de la casa (idéntico a gruls-ivol).

**Agregador (tabla de verdad, sin escotillas)**: H14 avanza a F3 ⟺ H-A pasa ∧ H-C pasa.
F3 pasa ⟺ H-B(i) ∧ H-B(ii). Cualquier falla en cualquier punto → el arco cierra documentando.
No existen caminos intermedios ni "sobrevivió lo esencial".

## §5 Sub-hipótesis, estadísticos y falsadores (sin filos de navaja)

### §5.1 H-A — el vaivén existe (condición necesaria)

Sobre el **estrato ejecutable** (§6), periodo de veredicto **2022+** (convención de la casa,
vara §8.1 de H13; la v1 usaba 2024+ elegido tras ver la serie anual — corregido por la crítica):

- **Estadísticos**: VR(2), VR(5), VR(10), VR(28) — estimador overlapping con corrección de
  sesgo, sobre log-retornos demeaned; z\* robusto a heterocedasticidad (Lo & MacKinlay 1988)
  + wild bootstrap (Kim 2006) porque cripto es GARCH extremo. ρ₁ con SE robusto. Persistencia
  de signo (definición de trend_study, ventanas no solapadas).
- **Agregación cross-seccional**: los símbolos van correlacionados ~0.8 → n_eff ≈ 1.25 sea
  cual sea n. La mediana del estrato es casi un solo draw del factor mercado → **toda decisión
  se toma con IC de bootstrap de bloques SOBRE FECHAS (bloques de 28d), nunca con el punto.**
- **Falsador H-A**: el IC 90% de la mediana del estrato de **VR(28)** queda enteramente ≥ 1.0,
  **o** el IC 90% de la mediana de ρ₁ queda enteramente ≥ 0.
  VR(28) manda por la identidad (verificada vs AR(1) en la crítica):
  **γ\*_rate(f) / γ\*_rate(1d) ≈ VR(f)** — el premio del reloj diario contra el lento depende
  de la varianza acumulada al horizonte lento, no solo del lag 1. (Neto de fees la reducción
  no es exacta — el costo escala ∝1/√f — pero con fees de futures 2-5bp el término es chico;
  la identidad se usa en bruto, y F3 carga los costos de verdad.)
- **Papel de cada estadístico**: VR(28) + ρ₁ = falsadores. VR(2,5,10) + persistencia =
  diagnóstico del perfil temporal. Se publican todos; ninguno extra decide.

### §5.2 H-C — vigencia (no es un fósil de 2021-23)

**Falsador H-C**: IC 90% (bootstrap de bloques sobre fechas) de la mediana de VR(28) del
estrato ejecutable en la submuestra **2024-07-01 → 2026-06-30 (24 meses, fija hoy)**
enteramente ≥ 1.0.

### §5.3 H-B — magnitud neta (SOLO F3, trial contado)

Corrección estructural de la crítica: el funding lo pagan AMBOS lados (el contrafactual B&H
en perps también lo paga) → se cancela a primer orden en la comparación; y pesa **×w** sobre
el NAV, no completo. Dos gates:

- **H-B(i) incremental**: premio de rebalancear vs no rebalancear (mismo venue, funding a
  ambos lados) ≥ **M×** su fricción incremental (fees × turnover; turnover exacto por paso:
  |Δw| = w(1−w)|r| / (1+w·r)).
- **H-B(ii) viabilidad absoluta**: crecimiento neto del sleeve (con w×funding realizado por
  símbolo y fees) > 0 en 2022+. La máquina debe ganarle a "nada", no solo a su gemelo.
- El margen **M** lo fija la vara de F3 que aprueba Erika (su gate) — no se fija aquí: la v1
  lo fijó en 2× DESPUÉS de conocer los niveles de funding, señalado como peeking por la
  crítica. El contrafactual B&H de un perpetuo (contratos constantes con funding drenando el
  cash del sleeve) se define operativamente en el pre-registro de F3.

### §5.4 Diagnósticos obligatorios SIN poder de veto (para que no queden radicales libres)

- **Concentración**: Lorenz/HHI de contribuciones **vs la esperada bajo γ\*∝σ²** (la
  concentración estructural en vol no es Simpson; el jackknife-top-10% de la v1 mataba una H
  viva por construcción y queda RETIRADO como falsador).
- **Mapa liquidez×vol**: premio estructural por tercil de vol × quintil de liquidez — el
  terreno donde Zaremba predice el cambio de signo. Es el instrumento que resuelve el prior.
- **Espécimen LUNA**: path real del colapso, con regla de liquidación declarada (§6).
- **Sesgo de supervivencia MEDIDO**: universo point-in-time con muertos = número oficial;
  la versión solo-sobrevivientes se computa únicamente para publicar la magnitud del sesgo.
- **Espécimen cartera propia**: VR/ρ₁ del path diario de la canasta whitelist (EW e ivol) y
  del libro shadow gruls-ivol (con el caveat n≈15 marks — anecdótico) — ¿el vaivén que Erika
  VE es del tipo cosechable? Responde la observación que motivó el arco.

### §5.5 Gemelos sintéticos (corregidos por la crítica)

Hallazgo verificado por álgebra: a f=1d, tanto el fixmix (∏(1+w·rₜ)) como el B&H dependen solo
del MULTICONJUNTO de retornos → **ambos son invariantes a permutación: el gemelo IID es
idéntico al real en la frecuencia titular**. La v1 proponía un control que no podía detectar
nada ahí. Diseño corregido:
- La invarianza a f=1 se usa como **test unitario de correctitud del código**.
- Gemelo IID (permutación): informa **solo f∈{2,5,10,28}**, con **≥100 réplicas en f∈{10,28}**
  (la varianza del estimador a f alto lo exige; a f bajo bastan 20).
- Gemelo block-bootstrap 20d (el de la casa, `mountains.synthetic_twin`): **SOLO f=28** — a
  f≤10 conserva la autocorr corta y reproduce el efecto que pretende controlar.
- Lema de la casa: *"lo que el gemelo reproduce NO es estructura de mercado; solo el residuo
  cuenta."*

### §5.6 Convenciones (fijadas hoy; la identidad VR↔γ\* no cierra sin ellas)

VR sobre log-retornos demeaned, estimador overlapping con corrección de sesgo. Crecimientos
sobre retornos simples. Premios anualizados en %/año. γ\* analítico de contexto =
½·w(1−w)·E[r²] (segundo momento crudo, no σ² — en discreto el término μ² no es despreciable
a f alto). E|r| = σ·√(2/π) se usa solo como cota gaussiana declarada.

## §6 Universo "todo el mercado" — anti-supervivencia, point-in-time (verificado 2026-07-26)

- **Fuente**: archivo público `data.binance.vision` (abre desde us-central1 — estrena el
  reemplazo del cable local anotado en DESIGN_H13 §11 como housekeeping futuro). Verificado
  directo contra el listing S3: **825 perpetuos USDT-M históricos** (vs 720 activos en
  exchangeInfo — 123 en SETTLING ahora mismo por una ola de delisting en curso); los
  deslistados CONSERVAN klines y funding (LUNAUSDT termina en su colapso 2022-05; SRM/ANC/DGB
  presentes). FTT NO es ejemplo de muerto: su perp siguió cotizando hasta 2026.
- **Exclusiones**: 144 TRADIFI_PERPETUAL (acciones tokenizadas), variantes `_SETTLED` y
  quarterlies con sufijo de fecha, pares BUSD/USDC (duplicados del subyacente).
- **Datos**: klines **diarios** (no 1h — H14 no los necesita) + funding mensual (la columna
  `funding_interval_hours` viaja al dataset: hay símbolos a 4h). Destinos:
  `bronze/vision_um_daily/`, `bronze/vision_funding/`, `datasets/market_daily_v1.parquet`,
  `datasets/market_funding_v1.parquet`. **El corpus H13 (`daily_v1.parquet`) no se toca.**
- **Reglas point-in-time (escritas hoy)**:
  - Un símbolo ENTRA al universo evaluable tras **60 días de historia** (30 para la métrica
    de liquidez + buffer).
  - SALE de su sleeve al **último close negociado antes de la suspensión** (si Binance publica
    settlement price, la diferencia se reporta como sensibilidad, no decide).
  - **Estratos de liquidez**: quintiles de quote-volume mediano rolling 30d, recalculados
    MENSUALMENTE con datos hasta el fin del mes anterior (cero lookahead).
  - **Estrato ejecutable (congelado HOY, no en F0)**: quintiles 4-5 (top-40%) — donde viven
    la whitelist y los mínimos del venue.
- **Chequeo cruzado de vía de datos**: σ y ρ₁ de los 29 símbolos del corpus H13 calculados de
  Vision deben coincidir con `daily_v1.parquet` (tolerancia 1e-2) — caza errores de
  tz/resampleo (la trampa de H8).

## §7 Aritmética de factibilidad ex-ante (publicada ANTES de correr, con números ya medidos)

Con w=½: γ\* analítico = σ²/8 por día. Fricción incremental (fees 2-5bp × turnover ≈ 0.2σ/d)
= 4-18bp/año — trivial. La viabilidad absoluta H-B(ii) carga w×funding realizado. Funding
medido HOY de los zips oficiales (2023-01→2026-06): BTC 7.30%/año, ETH 7.55%, SOL 3.89%,
AVAX 5.10%, DOGE 8.28% — el baseline 0.01%/8h (=10.95%/año) de `h13_eval` sobreestima: el
realizado es el 36-76% del baseline según símbolo.

| σ diaria | γ\* bruto/año | vs w×funding típico | Lectura ex-ante |
|---|---|---|---|
| 2% (BTC) | ~1.8% | ~3.7% | **No paga ni el funding — muerto ex-ante** |
| 4% (major volátil) | ~7% | 2-4% | Margen fino — la zona de la verdad |
| 6-8% (alt medio) | ~16-29% | 2-4% | Paga de sobra — PERO es donde Zaremba predice momentum (H-A muere) y la liquidez adelgaza |

La H solo puede vivir en la franja media de vol×liquidez. Ese es el prior del ~15% en números;
el mapa de F2a (§5.4) es el instrumento que lo resuelve.

## §8 Colisión con la regla ⛰️ y convivencia con el libro vivo (explícita, no por debajo)

- La ⛰️ (DESIGN_H12 §3, "en piedra") fija: cadencia de ajuste = horizonte del label ENTRENADO,
  "sin excepciones, sin banda diaria encima" — y gobierna "backtest Y pipeline productivo".
  §14.2 del watchdog además se auto-prohibió "inventar una segunda regla de rebalanceo no
  registrada". Un fixmix diario parece chocar de frente. Resolución:
- **F2a no la toca** (cero posiciones, cero cadencia — son estadísticos).
- **La enmienda a §3-H12 se aprueba ANTES de correr F3** (no "al llegar a producción": F3 ya
  backtestea una cadencia). Contenido de la enmienda: (a) la mezcla fija pura no tiene label
  entrenado — la letra de la regla es vacía para reglas mecánicas; (b) la cadencia evaluada
  queda FIJADA en f=1d por este pre-registro (no es cheque en blanco anti-cadence-shopping);
  (c) la razón de fondo de la ⛰️ (gap entrenar/operar) no aplica porque no hay nada entrenado.
  **Gate de Erika** (uno de los que sobreviven a su directiva de autonomía).
- **Convivencia**: si H14 llegara a operar, su sleeve va en subcuenta/cartera SEPARADA del
  libro gruls-ivol 28d — jamás neteado con él (sería la "banda diaria encima" prohibida).
- **La variante inclinada por el GRU queda FUERA de H14** (mezcla dos relojes con señal
  entrenada; sería H15 con planteamiento propio — y con el hallazgo BTC-sin-señal-absoluta
  del 2026-07-25 ya en la mesa).

## §9 Presupuesto y ejecución

Branch `feature/h14-harvest-eda`. Todo experimento corre en GCP (job `hermes-lab`,
us-central1); local solo orquesta. Costo estimado F1+F2a: **<$1** (build de imagen + job
30-60 min + storage <1GB). Gasto del arco acumulado ~$17 de $232 permitidos. LLM $0.
Módulos nuevos: `src/lab/market_corpus.py` (F1), `src/lab/harvest_structure.py` (F2a), con
tests unit (VR de AR(1) ≈ teórico; invarianza a permutación a f=1; PIT sin lookahead;
exclusiones y reglas de entrada/salida). Infra: imagen `lab:v30`, job apuntado, y se paga la
deuda documentada de `TF_VAR_lab_image` (drift v25→v29→v30).

## §10 Reporte obligatorio de F2a (sin gate, para el expediente)

Tabla maestra símbolo×año×estrato (σ, ρ₁±SE, VR(2,5,10,28)±IC, persistencia); veredicto
H-A/H-C con sus IC; gemelos (residuo por frecuencia); mapa liquidez×vol; los 5 diagnósticos
§5.4; cobertura y calidad del corpus (símbolos, huecos, muertos, cruce vs daily_v1). Página
Artifact didáctica para Erika (estándar EDA de la casa). Reportes:
`reports/h14_structure.{json,md}` en el bucket de research.

## §11 Registro de la crítica adversarial v1→v2 (parte del expediente)

1. **Benchmark confundido**: la v1 llamaba γ\* al premio vs B&H y lo respaldaba con un teorema
   que aplica a otro benchmark; bajo random walk su estadístico es ≈0/negativo (Monte Carlo).
   → v2: VR<1 elevada a condición necesaria; dos benchmarks explícitos (§1.1).
2. **Control vacuo**: el gemelo IID es idéntico al real a f=1d por álgebra (invarianza a
   permutación). → v2: gemelos solo informan f≥2; la invarianza pasa a test de código (§5.5).
3. **Funding mal asignado**: se cancela contra el contrafactual B&H y pesa ×w; la v1 lo
   cargaba entero y solo al fixmix — mataba majors por error contable. → v2: gates
   H-B(i)/(ii) (§5.3).
4. Frontera descriptivo/económico corrida (γ\* neto costeado "sin contar") → v2: todo
   veredicto económico es F3, trial contado (§4).
5. Sin particiones ni juez virgen → v2: §2.
6. "Régimen 2024+" elegido post-hoc tras ver la serie anual → v2: veredicto 2022+ (convención
   de la casa) + H-C con ventana fija de 24 meses (§5.2).
7. Jackknife top-10% garantizado a disparar (γ\*∝σ² concentra por construcción) → v2:
   degradado a diagnóstico vs concentración esperada (§5.4).
8. Falsadores de filo de navaja con n_eff≈1.25 → v2: toda decisión con IC de bootstrap de
   bloques sobre fechas (§5.1).
9. Escotillas cerradas: spot como puerta trasera (§4.2), estrato ejecutable definido hoy
   (§6), fecha de corte fija (§2), reglas de delisting escritas (§6), autopsia del watchdog
   citada (§3.3), numerario resuelto (§4.3), enmienda ⛰️ movida a antes de F3 (§8), margen M
   de H-B diferido a la vara de Erika (§5.3).
