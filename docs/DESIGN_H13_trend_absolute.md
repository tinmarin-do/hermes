# DESIGN H13 — Retorno absoluto bidireccional: TSMOM long-short + capa de arquetipos

**Pre-registro del arco. Commiteado ANTES de cualquier corrida (regla de la casa).**
Decisión de Erika 2026-07-13 (plan aprobado esa madrugada). Sustituye como arco activo
a H11/H12; hereda TODO el aparato anti-overfit.

## 1. Identidad y objetivo

El objetivo del research vuelve a su forma original: **retorno absoluto del movimiento
del mercado, en ambas direcciones** ("energía cinética") — no selección relativa, no
defensa, no "canasta con frenos" (rechazada explícitamente por Erika 2026-07-13).

Mecanismo elegido tras literature review (2026-07-13): **time-series momentum (TSMOM)
long-short** — señal por activo `signo(retorno de lookback)`, posición vol-escalada,
largo si tendencia arriba y corto si abajo — **+ capa de regímenes/arquetipos** para el
talón de Aquiles conocido (whipsaw en laterales). Evidencia externa: Moskowitz/Ooi/
Pedersen 2012 (Sharpe 1.28 en 58 futuros, 1985-2009); Hurst/Ooi/Pedersen (positivo cada
década desde 1880, 8/10 crisis); documentado en cripto (Liu & Tsyvinski; evidencia con
caveats de look-ahead en algunos papers — por eso se falsifica en NUESTRO harness).

**Dato de partida honesto**: en 21 trials de H11/H12 nunca probamos TSMOM puro — todo
fue cross-seccional long-only. La evidencia externa NO cuenta como evidencia nuestra.

## 2. Particiones de datos (fijas, no renegociables mid-arc)

| Partición | Rango | Rol |
|---|---|---|
| **Iteración** | 2021-01-01 → 2025-09-10 | Todo el diseño, EDA, trials, ajustes viven aquí. "2026 no existe" durante la iteración. |
| **Firewall (slice)** | 2025-09-11 → 2026-06-12 | One-shot, UN intento por candidato congelado. ⚠️ Ver §2.1. |
| **Forward** | post-pase del slice | Shadow corto 2-3 semanas en el venue nuevo (mini-forward virgen). |

### 2.1 ⚠️ Caveat de contaminación del slice (documentado para siempre)

Este slice fue QUEMADO por el one-shot del GRU (H12 §14, 2026-07-12). El operador
(Fable) conoce su contenido a detalle: régimen bajista (canasta EW −9.0%/periodo),
qué símbolos cayeron y cuánto. Un diseñador que sabe que el examen es un bear puede
sesgar (aun sin querer) una estrategia long-short hacia ese examen. **Erika aceptó
reusarlo (AskUserQuestion 2026-07-13) con estas compensaciones obligatorias:**

1. **Spec completa congelada y hasheada ANTES de cualquier evaluación en el slice.**
2. **Vara fijada ex-ante** (§8) usando SOLO literatura + periodo de iteración.
3. **Este caveat viaja con el resultado**: cualquier pase se reporta siempre como
   "pase en slice de segunda mano", nunca como evidencia virgen.
4. **El pase NO abre dinero real por sí solo**: obliga el shadow corto forward (§9.3),
   que es la única evidencia 100% virgen del arco.

## 3. Metodología heredada (vigente, sin cambios)

- **Trials contados**: `experiments/trials.jsonl` acumulativo; n_trials=21 al abrir el
  arco. Todo config evaluado economicamente cuenta. DSR con n acumulado.
- **Evaluación estándar**: `window_check` (40 ventanas 28d aleatorias purgadas, seed 42,
  2021-2025 — mismas ventanas para todos los candidatos) + corte temporal del periodo
  de iteración. Método consagrado por Erika ("nuestro método ganador").
- **Dónde-no-ir heredados**: no verdict-shopping; varas jamás se ablandan post-resultado;
  nada se flipea de signo post-hoc (#17); un solo intento por slice; pre-registrar antes
  de correr; cadencia productiva = horizonte entrenado (⛰️ regla en piedra §H12).
- **Intocables**: pipeline live (`src/brain/`, allocator, comité, scheduler) sin diffs
  salvo imports puros; el live Bitso actual (campeón momentum) opera INTACTO hasta F7.
- **Nota de cierre H12**: defense_check §15 quedó pre-registrado pero ENTERRADO sin
  correr (decisión Erika: no quiere blindaje long-only). 0 trials añadidos. La branch
  `feature/h12-defense-check` queda congelada como registro. Los shadows GRU y ext5-h28
  siguen emitiendo como baselines vivos del forward.

## 4. Fases

F0 pre-registro (este doc) → F1 auditoría de venue ∥ F2 EDA didáctico → F3 vara (gate
Erika) → F4 TSMOM trials → F5 capa de regímenes → F6 firewall → F7 wiring. Gates de
Erika: venue (F1), número de la vara (F3), sign-off (F6), tamaño completo (F7).

## 5. F2 — EDA exhaustivo y didáctico (descriptivo; NO cuenta al DSR)

Requisito explícito de Erika: paso a paso, gráfico, pedagógico ("para estar al nivel y
cachar detalles"). Cada capítulo se entrega como página Artifact con gráficas. Corre
sobre el corpus existente (Binance 29 símbolos 1h 2021→hoy, bucket de research).
Un análisis descriptivo no cuenta al DSR, pero **cualquier regla que después se evalúe
económicamente SÍ cuenta como trial**.

### 5a. Catálogo de montañas (idea de Erika, pre-registro del protocolo)

- **Segmentación**: ZigZag multi-tolerancia (grilla de tolerancias pre-fijada en el
  módulo, p.ej. {5%, 10%, 20%, 35%}) sobre cierres diarios. Cada tolerancia = una capa
  del catálogo. Una "montaña" = excursión valle→pico→valle a esa tolerancia.
- **Taxonomía SIN escala** (decisión Erika): la identidad de un espécimen es su FORMA
  normalizada (tiempo → [0,1], amplitud → [0,1]); su duración y altura reales se
  ARCHIVAN como atributos (para la transformación inversa y la segunda pregunta:
  ¿chicos y grandes del mismo tipo se comportan igual?).
- **Pregunta falsificable central: ¿continuo o grumos?** Fractal puro → continuo suave
  de formas sin tipos preferidos. Grumos (clusters de forma más densos que lo que el
  azar permite) → arquetipos reales. Métricas de validez de cluster + estabilidad.
- **Control de gemelos sintéticos**: mismo catálogo sobre series sintéticas con la misma
  estructura de volatilidad (block-bootstrap y/o GARCH surrogates). Lo que el gemelo
  reproduce NO es estructura de mercado. Solo el residuo cuenta.
- **Curva de identificabilidad**: para cada montaña histórica, en cada fracción de su
  desarrollo (usando SOLO la ladera izquierda), qué tan bien se infiere (tipo, fase,
  escala) y cuánto movimiento quedaba. Responde la pregunta que decide el valor de todo:
  **¿la certeza llega antes o después que el dinero?**
- **Canary anti-hindsight** (test unit): segmentar la serie truncada en t == segmentar
  la serie completa restringida a ≤t. Si el futuro cambia la segmentación del pasado
  visible, la feature es inutilizable en vivo.

### 5b. Estructura de tendencia (prerequisito TSMOM)

Autocorrelación de retornos por horizonte (1d→126d) por símbolo/año; persistencia de
signo (¿signo(ret pasado k-d) predice signo futuro?); vol clustering; dependencia de
régimen (hallazgo previo a confirmar o refutar aquí: el momentum muere en vol alta).

## 6. F4 — TSMOM en el harness (pre-registro de la grilla)

- **Motor nuevo** `src/lab/trend_backtest.py` (long-short; el motor long-only de H11 no
  se toca). Señal por activo: `signo(ret_lookback)`. Posición: `±k/σ_i` (vol-scaling
  canónico, EWMA λ=0.94 como referencia del live, re-implementado puro en lab), con
  límite de apalancamiento bruto total pre-fijado en la spec.
- **Grilla CERRADA antes de correr**: lookbacks **{21, 63, 126} días** — 3 configs base.
  Cadencia de rebalanceo = horizonte de la señal (⛰️). Cualquier config extra que se
  quiera después requiere enmienda pre-registrada ANTES de correrla.
- **Costos**: fees del venue elegido en F1 (maker/taker reales) + funding estimado del
  histórico del venue + sensibilidad slippage. Sin costos no hay trial válido.
- **Contabilidad en MXN** (regla de la casa) vía USDMXN, como todo el lab.

## 7. F5 — Capa de regímenes (condicional a F2)

Si el catálogo encuentra grumos → arquetipos como condicionador de exposición TSMOM.
Fallback estándar si no: jump-model/HMM de 2-3 estados (tendencia/lateral/turbulento).
Regla de decisión pre-registrada: la capa entra SOLO si mejora al TSMOM crudo bajo la
misma vara en window_check; si no mejora, se documenta y queda fuera. Cada variante
condicionada = trial contado.

## 8. F3 — Vara del arco (se fija ANTES del primer trial; gate de Erika)

El 1% diario queda formalmente enterrado como meta (decisión Erika 2026-07-13: "es
demasiada exigencia... la ajustaremos a expectativas no fantasiosas"). La vara numérica
se deriva en F3 de: banda de literatura (Sharpe neto TSMOM ~0.5-1.0, maxDD 15-30%, win
rate 30-40%) + base rates del periodo de iteración. Principios ya fijados:
- Se mide NETO de todos los costos, en MXN.
- Debe exigir desempeño en AMBAS direcciones (que el resultado no sea beta larga
  disfrazada: contribución de la pierna corta reportada por separado).
- Retorno ABSOLUTO como criterio primario (no exceso vs canasta — ese fue H12).
- **Erika aprueba el número explícitamente antes del primer trial de F4** y queda
  escrito aquí como enmienda §8.1.

## 8.1 Enmienda F3 — VARA APROBADA (Erika, 2026-07-13, ANTES del primer trial)

Sobre las 40 ventanas estándar del window_check (seed 42), retorno NETO absoluto
por ventana de 28d, todos los costos incluidos. Marco temporal decidido por Erika:
**2021 = prueba de estrés; veredicto principal sobre 2022+** (33 ventanas).

| # | Criterio | Exigencia |
|---|---|---|
| W1 | Economía moderna | mediana neta > 0 **y** media neta ≥ **+1.0%/ventana** en 2022+ |
| W2 | Consistencia | ningún año 2022-2025 con media neta < **−1.5%/ventana** |
| W3 | Estrés 2021 | media neta 2021 ≥ **−3.0%/ventana** |
| W4 | Energía cinética | mediana neta ≥ **0** en ventanas 2022+ donde la canasta cayó |

Anclas de calibración (registradas al aprobar): canasta 2022+ media +0.84%/σ 18.8%
por ventana; W1 ≈ +13-14%/año neto ≈ Sharpe ~0.5 con vol-target 25% (piso de la banda
de literatura). Reporte obligatorio sin gate: DSR (n acumulado), turnover, sensibilidad
slippage, contribución por pierna (para candidatos L/S la pierna corta se reporta
separada — no puede ser pasajera). **La vara no se ablanda post-resultado.**

## 13. Enmienda post-EDA (2026-07-13) — redirección del centro de gravedad

Resultados de F2 (EXPERIMENT_LOG mismo día): montañas = CONTINUO (arquetipos de forma
falsificados); prima de tendencia cruda INESTABLE (Simpson por composición de régimen;
ex-2021 ≈ 0 o negativa). Consecuencias pre-registradas ANTES de correr F4:

1. **F4 (TSMOM) queda degradada a verificación de cierre** — prior honesto bajo
   (~15-25%); se corre por pre-registro y para cerrar la pregunta con datos.
2. **F4b (NUEVA) = candidato principal: spread LONG-SHORT cross-seccional del GRU
   congelado** (`models/h12-gru-h28.json`, sha 4a52a1d4, receta §7.1 H12 intacta —
   re-entrenado por ventana con purga/embargo idéntico a window_check §13). Largo top-5 /
   corto bottom-5 del universo operable; neutral al mercado por construcción (mata el
   factor único — la enfermedad raíz de todo lo falsificado). Bottom-5 jamás medido:
   ese es el experimento. Grilla CERRADA: pesos por pierna ∈ {EW, inverse-vol} — 2
   configs. Gross 1.0 (0.5 por pierna), net 0.
3. **Costos pre-registrados (F4 y F4b)**: taker Binance futures 0.05% × entrada+salida
   sobre gross; funding conservador 0.84%/28d (0.01%/8h) aplicado SOLO como costo al
   |net exposure| (jamás como crédito); buffer de funding 0.1%/ventana para el libro
   neutral; sensibilidad slippage +10bps reportada.
4. **Juez para la familia GRU**: el slice quemado vale MENOS aún para F4b (la familia ya
   consumió ese examen en H12 §14) → el juez primario del L/S es el **shadow forward**
   (corre desde 2026-07-11, guarda rankings completos → el libro L/S es computable
   retroactivamente del ledger). El one-shot en slice queda como evidencia secundaria
   con doble caveat.
5. **Criterios de aborto del arco**: si F4 falla la vara §8.1 Y F4b no la pasa en 2022+,
   el arco CIERRA documentando que el set de señales actual no financia retorno
   absoluto. Hermes sigue live (campeón + shadows); research se pausa o pivotea a data
   nueva (funding rates/carry — hipótesis futura fuera de este arco).
6. Trials nuevos: 3 (TSMOM lookbacks {21,63,126}) + 2 (L/S {EW, ivol}) = 5 → n_trials
   21→26. Huellas del catálogo (asimetría por escala, valle derecho) = priors de diseño
   para F5, no señales; certificarlas requeriría gemelos por-escala (pendiente, barato).

## 9. F6 — Firewall (NO iterable)

1. Freeze del candidato: spec + parámetros hasheados → `models/` (sha256 verificado
   antes de puntuar, patrón H12).
2. One-shot en el slice de §2 con las compensaciones de §2.1. UN intento. Si falla:
   candidato muerto, se documenta, y el arco decide con Erika si hay candidato B
   legítimo (que NUNCA haya visto resultados del slice) o se cierra.
3. Si pasa → **shadow corto 2-3 semanas en el venue nuevo**: señales diarias congeladas
   contra precios reales del venue, sin dinero. Valida el puente de datos del venue Y es
   el único forward 100% virgen. Vara del shadow: pre-registrada junto con §8.
4. Sign-off explícito de Erika con el paquete completo (window_check + one-shot con
   caveat + shadow corto).

## 10. F7 — Wiring a productivo (post-sign-off)

- Adapter nuevo del venue de futuros (patrón `src/execution/bitso.py`), con guardrails
  NUEVOS para short/margen: margen AISLADO, buffer de liquidación, monitor de funding,
  límites de posición por símbolo y brutos, kill switch extendido a posiciones cortas.
- Scheduler productivo a la cadencia del horizonte entrenado (⛰️ — bloqueante, no opcional).
- **Plomería en chiquito** (decisión Erika): testnet o tamaño mínimo real (~$20-50 USD)
  durante 1-2 semanas ANTES de tamaño completo — caza bugs de ejecución/margen/funding/
  liquidación. La estadística no sustituye la prueba de tubería.
- La migración del capital del live Bitso actual la decide Erika en ese momento.

## 11. Enmienda F1 — venue decidido (2026-07-13, gate de Erika cerrado)

**Binance USDT-M Futures, ejecutor en `europe-west1`.** Sondas Cloud Build
(2026-07-13, `reports/venue_futures_audit.md`): el 451 de Binance es por región US,
no por GCP — desde europe-west1 abren spot y futuros (200); el testnet de futuros
abre incluso desde us-central1 (plomería F7 sin mover región); Binance Vision CDN
abre en todas las regiones (candidato a reemplazar el cable local del corpus —
housekeeping futuro). Ventaja metodológica decisiva: **mismo venue que el corpus
histórico** → las señales se entrenan y ejecutan sobre los mismos precios; el
puente de tracking (necesario con Bitso en H11) deja de existir. Fees 0.02%/0.05%
(≈7× más barato que Bitso spot). Pendiente del lado de Erika: abrir cuenta y key
**read-only** (jamás retiro, regla #4). Solo el job/adapter de ejecución vivirá en
europe-west1; el laboratorio queda en us-central1.

## 12. Presupuesto del arco

Jobs de EDA + trials TSMOM ≈ $0.05-0.10 c/u → estimado total **$5-15 USD** adicionales
(gasto acumulado ~$13 de $290; tope duro 80% = $232). Protecciones del arco H11 vigentes
(billing budget 50/80%, EXCLUDE_ALL_CREDITS).

## 9.1 F6 en ejecución (2026-07-13, decisión Erika: "Vámonos de una vez con F6", F5 saltada)

**Candidato congelado**: `models/h13-gruls-ivol.json` —
sha256 `0dac692a2016ba891f753a33281a686383ce8cb78fd9a5c3c4d2dea3b99e9354`.
Estrategia sobre el artefacto GRU ya congelado de H12 (sha `4a52a1d4…`, SIN retoques):
top-5 largo / bottom-5 corto, pesos ivol (σ 20d), gross 1.0, net 0, cadencia 28d (⛰️),
costos §13.3. F5 (capa de regímenes) queda saltada por decisión — puede revisitarse
post-firewall como mejora, jamás como rescate.

**Vara del one-shot SECUNDARIO en el slice (pre-registrada AQUÍ, antes de correr)**:
modo deployment (el artefacto congelado puntúa; CERO re-entrenos), 28 fases escalonadas
(offsets 0..27, hold 28d), economía L/S con costos §13.3 por periodo (entrada+salida
completa cada rebalanceo — conservador):
- **S1**: media entre fases del neto por periodo > 0.
- **S2**: ≥ 55% de fases con neto medio positivo.
**Doble caveat permanente**: (a) el slice fue consumido por esta MISMA familia (one-shot
GRU §14 de H12) — este resultado es evidencia DÉBIL gane o pierda; (b) el operador
conoce el contenido del slice. Por ambos, el veredicto S1/S2 NO abre nada por sí solo:
es un dato del expediente. **El juez primario es el shadow forward** (§9.1b).

**§9.1b — Shadow L/S (juez primario)**: el ledger multi-stream (corre desde 2026-07-11,
ancla de grilla 07-11) guarda p y precios de TODO el universo por día → el libro
h13-gruls-ivol se reconstruye retroactivamente desde el ancla y se marca a diario.
Evaluador: `src/lab/shadow_spread.py` (on-demand). Ventana mínima de juicio antes del
sign-off: 2-3 semanas de marks diarios (plomería estadística: tracking sano, sin
anomalías) — la significancia estadística NO es exigible en 3 semanas y no se
pretenderá; la exigencia es consistencia con el expediente y cero sorpresas
operativas. Sign-off de Erika = gate final antes de F7.

## 10.1 F7 en ejecución — WA aprobado por Erika (2026-07-13, "hoy comenzamos con fondos")

**Re-secuencia aprobada**: F7 se construye YA, en paralelo con la maduración del shadow
(el juez no se recorta — madura mientras la plomería trabaja). Timeline: adapter+infra
hoy → testnet ~16-17 jul → plomería REAL ~17-18 jul → sign-off ~27 jul (shadow 2+
semanas + bitácora de plomería) → cartera completa post-firma con entrada catch-up al
libro vigente; primer rebalanceo natural de grilla 2026-08-08 (ancla 07-11, ⛰️).

**Decisiones de Erika registradas**:
- **Budget dinámico = wallet** (regla suya, idéntica al live Bitso): lo que exista en el
  wallet de futuros se considera disponible; el ejecutor dimensiona el libro con el
  balance del momento.
- **Piso físico de plomería: $60-100 USDT** (Binance MIN_NOTIONAL ~5 USDT × 10 patas;
  con $1 el venue rechaza las órdenes — imposibilidad del exchange, no política).
  Guardrail: si el balance no alcanza para las 10 patas con mínimos, el ejecutor se
  queda en CASH y alerta — jamás arma un libro mocho.
- Sin apalancamiento en plomería (1x, margen AISLADO por posición).

**Arquitectura del ejecutor (una sola fuente de verdad)**: el ejecutor NO re-calcula la
señal — lee el entry diario del shadow ledger (`shadow/h12-gru-h28/days/`), que ya emite
p de todo el universo a las 00:20 UTC, construye el libro ivol de la spec congelada
`h13-gruls-ivol` (sha verificado) y reconcilia la cuenta de futuros contra ese target.
Shadow y live no pueden divergir por construcción. Corre 00:40 UTC en europe-west1
(job dedicado; el pipeline live de Bitso NO se toca). Mapeo símbolo→perp verificado
contra exchangeInfo en runtime (símbolo sin perp → se excluye y alerta).

**Guardrails nuevos (short/margen), todos bloqueantes**: margen aislado 1x · verificación
MIN_NOTIONAL/LOT_SIZE pre-orden · límite de posición por símbolo (≤15% del wallet) ·
kill switch extendido (cierra TODAS las posiciones, largas y cortas, a market) ·
monitor de funding acumulado · alerta email vía canal existente. La key de trading
NUNCA tiene permiso de retiro (regla #4).

## 10.2 Desviación SOLO-PLOMERÍA (decisión Erika 2026-07-13: "plomería reducida con los $100")

Hallazgo de la plomería (dry-run real): las patas mínimas del venue son BTC $62,
ETH/LTC/BCH $20, resto $5-6 → el libro completo 5+5 exige wallet ~$620 (ew) /
~$450 (ivol). Con $100 se pre-registra **PLUMBING_MODE** en el ejecutor:
- Universo de plomería = símbolos del libro vigente cuya pata mínima
  (max(min_notional, step×mark)) quepa en el 15% del wallet → hoy 6 baratos.
- k adaptativo = min(5, ⌊n_asequibles/2⌋), mínimo 3 — si no, CASH.
- Pesos EW forzados (determinista), gross 0.9 (patas de 15% exacto, dentro del cap).
- **Propósito EXCLUSIVO: mecánica** (órdenes, margen aislado, reconciliación,
  funding, kill switch). Sus resultados NO son evidencia de performance de la
  estrategia y NO tocan el expediente. El libro real 5+5 se estrena con la
  cartera completa (~$650+; desde agosto, con σ del ledger madura, ~$450 con ivol).
- PLUMBING_MODE es un env del job, default OFF: producción conserva
  libro-completo-o-CASH sin excepciones.

## 14. Enmienda — salida por precio (watchdog) sobre `gruls-ivol` (2026-07-24, pre-registro)

Idea de Erika (conversación 2026-07-24): capturar "energía cinética" en ambas direcciones
sin esperar los 28 días completos — soltar una posición cuando el precio ya dio el
movimiento buscado, en vez de sostenerla hasta el próximo rebalanceo pase lo que pase.

### 14.1 Precedente — por qué esto NO es una repetición ciega

H11 ya probó take-profit/stop-loss a nivel FIJO ±3% sobre el clasificador diario
(`src/lab/backtest_daily.py`, `StrategyParams.stop_loss`/`take_profit`, chequeo a 1 día
vista vía `fwd_high_ret`/`fwd_low_ret`) y lo enterró con evidencia
(`docs/EXPERIMENT_LOG.md` — TP+3%: +0.164%→−0.086%/día; SL−3%: +0.169%→−0.022%/día;
`docs/DESIGN_H11_daily_classifier.md` §10.3): *"ningún mecanismo de salida intradía a ±3%
sobrevive en este universo — el nivel está dentro de la banda de ruido"*. Un nivel fijo
universal quedaba dentro de la vol diaria típica de cripto (~3-5%) y amputaba la cola
derecha que paga la estrategia. **No se re-mide sin mostrar esta evidencia** (regla de
la casa) — este diseño ataca directamente esa causa de muerte con dos diferencias:

1. El gatillo se evalúa sobre la ventana completa de 28 días (camino día a día), no un
   solo "¿tocó mañana?" a 1 día vista.
2. El umbral es **relativo a la vol de cada símbolo** (`sigma20` = `close.pct_change()`
   con `.rolling(20).std()`, la MISMA métrica que ya pondera la pierna ivol en
   `spread_leg_weights`, `src/lab/h13_eval.py`), no un porcentaje universal fijo.

### 14.2 Mecanismo

- **Cadencia de re-rankeo**: intacta, 28d (⛰️ — el GRU congelado sigue prediciendo a su
  horizonte entrenado; solo cambia CUÁNDO se cierra una posición ya abierta, no cuándo
  se vuelve a preguntar quién es top-5/bottom-5).
- **Monitoreo**: diario, dentro de cada ventana de 28d, usando los `close` diarios ya
  presentes en el panel de `load_panel` (sin ingesta nueva).
- **Gatillo por posición individual** (no a nivel de todo el libro): cada símbolo del
  libro (largo o corto) se cierra en cuanto su retorno acumulado desde `t0` cruza
  `+k·sigma20` (toma de ganancia) o `−k·sigma20` (stop de pérdida) — simétrico, ambas
  direcciones, con el signo de la pata ya aplicado (una pata corta gana con precio
  bajando). Si ninguno se cruza, se sostiene hasta el cierre natural del día 28.
- **Capital liberado**: queda en CASH hasta el próximo rebalanceo programado — no hay
  re-entrada intra-ventana (evita inventar una segunda regla de rebalanceo no
  registrada).
- **Se descarta explícitamente** el kill-switch a nivel de cartera completa (un solo
  símbolo rezagado retendría a los que ya quieren salir).
- **Costos**: mismos de §13.3 (`ROUNDTRIP`, `FUNDING_28D`/`FUNDING_BUFFER` de
  `src/lab/h13_eval.py`) — el cierre anticipado paga el mismo roundtrip que un cierre a
  28d, prorrateado por los días efectivamente sostenidos para el funding.

### 14.3 Grilla CERRADA (pre-registrada antes de correr)

`k ∈ {1.0, 1.5, 2.0}` (múltiplo de `sigma20`), simétrico TP/SL, sobre la pierna ganadora
de F4b (`ivol`, ya pasó §8.1). 3 configs. Cualquier config adicional requiere enmienda
pre-registrada nueva antes de correrla.

### 14.4 Vara

Bajo las mismas 40 ventanas purgadas de `window_check` (seed 42, purge/embargo 28d): la
mediana neta 2022+ del watchdog **no debe quedar por debajo** de la mediana neta 2022+ de
`gruls-ivol` sin watchdog (`net_median_modern` de `apply_h13_bar`, ya registrada en
`reports/h13_spread.json`) — mismo patrón que §7 F5 ("entra SOLO si mejora al crudo bajo
la misma vara"). Si no mejora, se documenta y queda fuera; la vara no se ablanda
post-resultado. Reporte obligatorio: contribución de TP vs SL por separado (cuántas
patas cerraron por cada motivo), para poder distinguir "capturó la cola derecha" de
"solo evitó pérdidas".

### 14.5 Conteo de trials

La construcción del motor y sus tests unitarios son ingeniería pura — no cuentan al DSR.
Correr la grilla de 3 configs bajo `window_check` SÍ cuenta: `n_trials` 26→29.
