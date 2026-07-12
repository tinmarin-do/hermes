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
