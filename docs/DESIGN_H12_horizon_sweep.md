# DESIGN H12 — Barrido de horizontes con label de extremos relativo (PRE-REGISTRO)

**Fecha:** 2026-07-12 · **Owner:** Erika · **Estado:** ABIERTO
**Antecedente:** arco H11 CERRADO con veredicto (EXPERIMENT_LOG): a horizonte 1 día no
hay alpha de selección sobre la canasta EW (14 trials, 3 familias de label, exceso
convergió −0.13 → −0.062 → −0.043 sin cruzar 0; precision@5 ≈ azar). Directiva de
Erika: "No me rindo" — probar el MISMO target ganador (extremos relativos) a
horizontes mayores, experimentando con el tamaño de la ventana.

## §1 Hipótesis

El label `extremes_k5` (top-5 vs bottom-5 relativo, banda media purgada) SÍ separa
ganadores de perdedores a horizontes de formación/tenencia mayores, donde (a) el ruido
diario se promedia, (b) la fricción por unidad de tiempo cae ~H×, y (c) las señales de
régimen (momentum vive en vol baja/media) tienen espacio. H9 falsificó regresión
semanal ABSOLUTA; la clasificación cross-seccional relativa semanal está virgen.

## §2 Grilla de horizontes — PRE-REGISTRADA, CERRADA

**H ∈ {3, 7, 14} días.** Los tres se corren SIEMPRE (nada de parar en el primero que
guste — anti horizon-shopping); H=1 ya está medido (H11) y sirve de fila baseline.
Extender la grilla = nueva enmienda con gate de Erika. Todos los trials cuentan al
DSR (n_trials continúa: 14 al abrir este arco).

## §3 ⛰️ REGLA EN PIEDRA — cadencia de producción = horizonte del target

**La periodicidad del ajuste de portafolio (backtest Y pipeline productivo) ES el
horizonte H del label con el que se entrenó. Sin excepciones, sin "banda diaria
encima".** Si el candidato ganador es H=7, Hermes rebalancea cada 7 días — la corrida
diaria podrá observar/loggear, pero NO ajusta el libro fuera de la grilla de
rebalanceo. El backtest lo aplica desde ya: decisiones SOLO en fechas t0, t0+H,
t0+2H… (bloques no solapados); el motor anualiza con PPY=365/H y el benchmark EW se
mide en la misma grilla. Razón: entrenar a una cadencia y operar a otra fue la fuente
del gap señal-ejecución del campeón momentum (validado semanal, operado diario con
banda — revisión pendiente 2026-08-05) y de TODO backtest-vs-live drift. Cualquier
promoción a producción incluye el cambio de scheduler ANTES del go-live.

## §4 Metodología (hereda H11 §4/§9/§10 con escalado)

- Label: `extremes_k5` sobre el retorno forward de H días en MXN (close→close
  compuesto con FX H-días). Canasta ≥ 11; banda media NaN (fuera del training);
  50/50 por construcción. El backtest puntúa TODAS las filas (anti-leakage §10.1).
- **Purga/embargo ESCALAN con H**: purga = max(1, H), embargo = max(5, H) — labels
  solapados train↔val = leakage directo (López de Prado).
- Split híbrido 80/20 idéntico (K=5 bloques mensuales + corte temporal); slice de
  confirmación (últ. 15%) INTOCADO — sigue virgen de H11.
- Features: FEATURE_SET_V2 como base, PERO cada horizonte pasa por su MINI-D1
  (IC contra el retorno relativo de H días) → dossier por horizonte → **GATE de
  Erika antes de entrenar**. Racional: a H=7/14 las ventanas de observación deben
  crecer (regla observación >> horizonte) — ret_21d/ret_63d (muertas a 1d) se
  re-juzgan por horizonte; candidatas de lookback < H quedan excluidas por la regla.
- Métricas/metas (heredan §9.2/§10.2, evaluadas EN LA GRILLA de H): accuracy > 0.55
  en ambas validaciones (extremos) · profit factor ≥ 1.5 · exceso vs B&H EW > 0 ·
  precision@5 reportada · PSR/DSR con n_trials acumulado. Mínimo 20 bloques de
  validación para métricas económicas (H=14 → ~24 bloques en el corte temporal).
- Salidas intradía: RETIRADAS (TP/SL enterrados en H11 — no se resucitan sin gate).

## §5 Firewall (idéntico a H11 §7)

Slice de confirmación one-shot + shadow forward ≥ 45 días A LA CADENCIA H + sign-off
de Erika. El live (campeón momentum, Bitso) NO se toca durante el arco. La promoción
incluye alinear el scheduler a H (§3) como parte del MISMO gate.

## §6 Presupuesto

Créditos restantes ~$285 de $290; regla dura 80% ($232) intacta. Costo estimado del
arco: <$10 (estudios + ~6-10 trials).

## §7 Fase NN — ACOTADA (pre-registrada 2026-07-12, aprobada por Erika)

Corre DESPUÉS del barrido baseline y SOLO sobre el horizonte ganador. **Máximo 2
configuraciones contadas** (techo duro anti-DSR; ampliar = nuevo gate):
1. **TTM (IBM TinyTimeMixers) fine-tuneado** a forecast de retorno H-días por símbolo
   → rank de predicciones → misma cartera top-5 (el prior pre-entrenado es la
   hipótesis; el forecaster no ve el label — la cartera lo convierte en ranking).
2. **Red pequeña supervisada (TCN/GRU)** sobre secuencias OHLCV crudas (60-90d) con
   label extremes_k5 (representation learning: ¿las features manuales pierden algo?).
Racional del techo: LightGBM > logística falló 3×— la capacidad no es el cuello de
botella; una red solo es hipótesis NUEVA si cambia el INPUT (secuencias crudas).
Mismo juez: metas §4, cadencia en piedra §3, conteo íntegro de trials. Cómputo: VM
spot (toggle Terraform) o Cloud Run GPU; créditos sobran.

## §8 Sets por horizonte — GATE CERRADO (Erika 2026-07-12: "Vamos a como me digas")

Regla lookback ≥ H aplicada; evidencia: dossiers `feature_dossier_v2_relmedian_h{3,7,14}`.
- H=3: rv_20d, ret_5d, ret_21d, ret_63d
- H=7: rv_20d, ret_10d, ret_21d, ret_63d
- H=14: rv_20d, ret_21d, ret_63d
Excluidas: ewma_vol_20 (canary FUGA ×3 — definitivo), breadth_20d (day-constant,
artefacto), hl_range/hl_range_z30 (lookback 1d < H; z30 muere con horizonte),
usdmxn_ret_5d (IC +0.032 a H7 pero lookback 5 < 7 — la regla manda).

## §9 Cambio de protocolo (2026-07-12, directiva Erika)

Erika descartó su gate de aprobación en decisiones de research ("no lo veo muy útil
— descartar de una"): dossiers, sets por horizonte y enmiendas de label dentro del
arco ya NO esperan su OK. El rigor NO cambia: sense-first, pre-registro fechado ANTES
de correr, conteo íntegro de trials, reporte honesto con caveats. La extensión de
grilla {21, 28} del §2 pasa a requerir solo enmienda pre-registrada (sin gate).
**El firewall del §5 (dinero real) queda INTACTO, incluido su sign-off explícito.**

## §10 Enmienda: grilla extendida {21, 28} (2026-07-12, pre-registrada; sin gate §9)

Motivación: phase check de H=14 PASADO (13/14 fases positivas, media +1.45%/periodo).
Pregunta: ¿el exceso crece con H o 14 es el pico? Se agregan H=21 y H=28 (se corren
AMBOS, grilla cerrada de nuevo). Reglas:
- Sets desde el mini-D1 por horizonte (dossiers _h21/_h28) con la regla lookback ≥ H
  (rv_20d queda EXCLUIDA a H≥21 — 20d < H; el universo elegible se reduce a
  formaciones largas: ret_21d/ret_63d/hurst_100d si el dossier los sostiene).
- **Evaluación económica primaria = media del phase check (todos los offsets)** —
  el holdout temporal solo da ~12-16 bloques por fase a estos H; el motor baja su
  mínimo a 10 periodos para H>14 y TODO resultado carga el caveat de n chico.
- Metas y firewall sin cambio. Trials contados (n=17 al pre-registrar).

## §11 METAS v3 (2026-07-12, aprobadas por Erika: "Ok") — reemplazan acc>0.55

- **M1** exceso phase-mean > 0 en los TRES horizontes {14,21,28} (anti H-shopping).
- **M2** PF ≥ 1.5 como phase-mean del horizonte candidato (anti fase-suertuda).
- **M3** ANTI-EPISODIO: exceso medio > 0 quitando el MEJOR bloque de cada fase
  (anti "un-rally-lo-es-todo" — los bloques +98/+174% obligan).
- **M4** AUC-ROC > 0.52 en ambas validaciones (piso de calidad de ranking;
  reemplaza acc>0.55, que mide frecuencia donde la estrategia vive de magnitud).
- **M5** pasar M1-M4 = ENTRADA al firewall §5 (one-shot slice virgen + shadow ≥45d
  a cadencia H + scheduler alineado + sign-off de Erika). Sin cambios.
Expectativa pre-registrada: el holdout fue año excepcional; confirmación/shadow
mostrarán menos. Un exceso robusto de +0.05%/día ya sería extraordinario.

## §12 Shadow pre-firewall del campeón ext5-h28 (2026-07-12, pre-registrado ANTES de la 1ª emisión)

Directiva Erika 2026-07-12 ("NO descartaría todavía al candidato... ha sido nuestro
mejor candidato"): `ext5-h28-logistic-20260712` es el CAMPEÓN del arco (M1-M3 ✅,
M4 ❌ por 0.0015 en bloques). El shadow forward es la única evidencia que puede
zanjar M4 sin verdict-shopping: papel, cero riesgo, NO consume el slice one-shot,
NO es el shadow ≥45d del firewall §5 (ese arranca formalmente cuando el candidato
entre al firewall; este pre-firewall acumula desde YA y sus días CUENTAN como
historia forward del mismo modelo congelado).

**Implementación** (`src/lab/shadow_producer.py`, modos --freeze/--emit/--eval):

1. **Freeze**: la receta del spec re-entrenada UNA vez sobre TODA la iteración
   (corpus Binance; el slice de confirmación jamás entrena — `partitions()` lo
   excluye). Artefacto JSON auditable con sha256 (μ/σ del scaler + coef + b), sin
   pickle → `models/h12-ext5-h28.json`. El sha se registra en cada emisión: si el
   modelo cambia, deja huella.
2. **Emisión diaria, rebalanceo cada 28d (⛰️ §3)**: scheduler 00:20 UTC dispara
   `--emit` (delta Bitso → features → p → ledger). La grilla de rebalanceo queda
   ANCLADA en la fecha de la primera emisión; día de grilla perdido → catch-up en
   la siguiente emisión SIN re-anclar. La emisión diaria de p solo acumula
   evidencia AUC — los pesos NO se tocan entre fechas de grilla.
3. **Universo y features = Bitso MXN nativo** (la caja registradora del arco):
   ~10 libros operables (NON_TARGET fuera). El modelo entrenó sobre Binance
   (~25 operables) — DESVIACIÓN DOCUMENTADA en dos frentes: (a) top-5 de 10 es
   menos selectivo que top-5 de 25; (b) con n=10 y k=5, extremes_k5 degenera a
   beats-median. Es EXACTAMENTE el universo que enfrentaría el live en el venue —
   el shadow mide la regla como operaría, no como entrenó. ret_63d desde closes
   MXN: el modelo es monótono en su única feature y el FX es factor común del día
   → el top-5 es idéntico al ranking USDT; ret_63d crudo se registra por símbolo
   para auditar el puente.
4. **Ledger en el bucket de research** (`shadow/h12-ext5-h28/days/<fecha>.json`),
   NO en el DuckDB del brain: state_sync sincroniza por download→modify→upload y
   un segundo escritor haría race con la corrida diaria live. Esquema espejo de
   `shadow_signals` — importable si se promueve. **El pipeline live no se toca.**
5. **Evaluación** (`--eval`, corre tras cada emisión → `reports/shadow_h12_ext5_h28.md`):
   track record con fees Bitso (0.36% + 10bps slippage sobre turnover DRIFTEADO —
   más realista que el backtest) vs benchmark EW buy&hold del universo; exceso por
   periodo de 28d. **AUC forward**: p emitida vs label realizado a 28d —
   **grilla = primaria** (apuestas independientes), diaria solapada = secundaria
   (obs correlacionadas, solo indicativa). Madurez con tolerancia +3d.
6. **Qué puede y qué no puede esta evidencia**: NO re-abre el M4 de bloques (los
   draws 2021-22 son los que son); aporta una línea NUEVA de evidencia fuera de
   muestra que Erika pondera en el sign-off. La vara del §11 NO se ablanda: metas
   fijas, el shadow solo suma datos. Expectativa pre-registrada: a 28d de cadencia
   cada periodo es UN punto económico — la lectura honesta temprana es el AUC
   diario indicativo + la direccional del primer periodo, nada más.

## §7.1 Config NN-1 CONGELADA (2026-07-12, pre-registrada ANTES de correr)

GRU supervisado sobre secuencias derivadas del OHLCV crudo (`src/lab/nn_trial.py`).
Instanciación honesta de "secuencias OHLCV crudas": canales ESTACIONARIOS derivados
1:1 del OHLCV (ret_1d, hl_range, vol_rel=log(vol/MA20)) — precios crudos no son
comparables entre símbolos; z-norm POR VENTANA (μ/σ de la propia secuencia, causal).

Hiperparámetros fijos (sin tuning; 1 config = 1 trial contado):
window=84 (≈ la formación ret_63d del campeón + margen) · GRU hidden=32, 1 capa,
dropout=0.2 · Adam lr=1e-3 · batch=256 · **épocas=15 FIJAS** (sin early-stopping
sobre validation — sería selección de modelo con el set de evaluación) · seed=42 ·
label extremes_k5 H=28 · threshold 0.5 · top-5. Split híbrido purgado a H=28 y
phase check completo (28 offsets) DENTRO del trial. Baseline a vencer (campeón):
exceso fase-media +5.02%/periodo, PF fase-media 3.14, sin-top1 +0.80, AUC bloques
0.5185 / temporal 0.5236. La config NN-2 (TTM fine-tune) congelará sus
hiperparámetros en §7.2 antes de SU corrida.

## §12.1 Segundo stream del shadow: GRU NN-1 (2026-07-12, pre-registrado ANTES de su 1ª emisión)

Tras el trial `nn1-gru-h28-20260712` (M1-M3 ✅ con margen, M4-bloques ❌ 0.5052 con
varianza 0.45-0.55), la adjudicación honesta entre campeón y challenger es forward:
ambos fallan M4 en histórico y el holdout fue año excepcional. El GRU entra al
shadow con el MISMO protocolo del §12 — congelado con la receta §7.1 re-entrenada
sobre toda la iteración (confirmación jamás entrena), artefacto JSON sin pickle
(state_dict como tensores planos + sha256), universo Bitso operable, cadencia 28d,
ledger y reporte propios (`shadow/h12-gru-h28/`).

Reglas anti-trampa del multi-stream:
1. **Mismas fechas de grilla y mismo universo** para todos los streams → la
   comparación es cara a cara, sin ventajas de calendario.
2. **Agregar streams NO multiplica boletos al firewall**: si algún día se
   promueve uno, la evidencia forward se lee CONTANDO cuántos streams compitieron
   (selection effect declarado; hoy: 2). Congelar un stream nuevo requiere
   enmienda §12.x pre-registrada, y sus días de shadow cuentan desde SU freeze —
   nunca retroactivos.
3. Los canales del GRU se computan de velas Bitso MXN (z-norm por ventana absorbe
   escala; caveat de venue idéntico al del campeón, documentado en §12.3).
4. El pipeline live sigue intocado; el slice one-shot sigue virgen.
