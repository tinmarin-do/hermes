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
