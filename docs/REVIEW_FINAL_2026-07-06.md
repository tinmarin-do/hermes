# Revisión final exhaustiva — 2026-07-06

**Auditora:** Claude Fable 5 (última sesión) · **Solicitada por:** Erika ("ultra quisquillosa,
a la altura de la ambición de Fable") · **Alcance:** proyecto completo.

---

## 1. Hallazgos ARREGLADOS en esta revisión (PR final)

| # | Severidad | Hallazgo | Fix |
|---|-----------|----------|-----|
| 1 | 🔴 **P0** | **Cadencia sin evidencia** (pregunta de Erika): el champion se validó SEMANAL (`W-MON`, PPY=52) pero producción opera DIARIO. Medido: evaluar diario aporta (+99.8% sin fees vs −23.9% semanal c/fees, 2024→hoy) pero el churn descontrolado es letal (−93%). | **Decisión Erika (opción B):** banda anti-churn `min_trade_frac` 1%→**5%** (`HERMES_MIN_TRADE_FRAC`) + panel turnover/fees mensual en snapshot + **revisión con track record en ~30 días**. Registro completo en EXPERIMENT_LOG. |
| 2 | 🔴 **P0** | **VaR era advisory:** `risk_facilitator` aprobaba por texto del LLM; un facilitador persuadido podía aprobar un trade que REPROBÓ el VaR calibrado (viola regla #4: los agentes solo frenan). | Gate duro: `var_ok=False` anula la aprobación del LLM, siempre. +3 tests (`test_risk_gate.py`). |
| 3 | 🟠 **P1** | **Guard anti-dup y freno de budget con tz mezcladas:** ts naive-UTC vs `current_date` LOCAL → el guard quedaba CIEGO cada noche 18:00-24:00 MX en hosts no-UTC (en cloud funcionaba solo porque el contenedor es UTC — suposición implícita). Cazado porque los tests fallaron a las 22:10 MX. | Fecha/mes UTC explícitos desde Python en ambas queries. |
| 4 | 🟠 **P1** | **Flip público obsoleto y peligroso:** `dashboard_public=true` (demos, pre-IAP) hoy expondría `/api/live` — balances reales de Bitso — a internet. | Retirado de TF por completo. Demos = viewer temporal en `dashboard_iap_accessors`. |
| 5 | 🟡 **P2** | **equity_curve contaminada:** corridas de validación/emergencia insertan puntos intradía → n inflado y horizontes mezclados en Sharpe/PSR de la "curva oficial 1 punto/día". | Dedupe a último-punto-por-día-UTC para la serie/métricas (la tabla cruda se conserva). |
| 6 | 🟡 **P2** | **Turnover invisible:** no había forma de juzgar el churn real de la cadencia diaria. | `_turnover_panel` en el snapshot: fills + notional + fees por mes (el juez de la decisión de cadencia). |

## 2. Hallazgos DOCUMENTADOS (decisión o trabajo futuro — priorizados)

| # | Prioridad | Hallazgo | Recomendación |
|---|-----------|----------|---------------|
| A | **Alta** | **TF apply puede apagar IAP** (provider estable ciego a `iap_enabled`; ocurrió 2026-07-04). Protocolo post-apply documentado en `terraform/modules/cloud-run/main.tf`. | Migrar el recurso dashboard a `google-beta` con `iap_enabled=true` — ciclo propio con calma. |
| B | **Alta** | **Cloud SQL ociosa = $8.60/mes = 86% del cap GCP.** Cero queries en producción (DuckDB-en-GCS es el estado real). | Decisión de Erika: `terraform destroy -target` de la SQL (~$1.15/mes total, libera margen) o justificarla portando el track record. Recomendado: **bajarla**. |
| C | **Alta** | **Branch protection IMPOSIBLE** en repo privado free-tier (por eso #20-22 mergearon con CI rojo — no fue config). | Repo público (alineado a la ambición portfolio; revisar que no haya nada sensible en historia — los secretos siempre estuvieron fuera) o GitHub Pro ($4/mes) o disciplina actual. |
| D | Media | **Cadencia: revisión en ~30 días** (≈2026-08-05) con el panel de turnover — si fees/mes ≫ ~4 rebalanceos semanales, alinear a semanal estricto (trades solo lunes; watchdog conserva permiso diario defensivo). | Agendado en §13 del PRD. |
| E | Media | Budget alert de GCP (prometido) — `google_billing_budget` necesita billing account ID + API. | Módulo monitoring ya existe; añadir cuando Erika comparta el billing account ID. |
| F | Media | El slot shadow corre heurística placeholder — el challenger de REGRESIÓN no existe aún. | Arco bake-off diseñado en memoria (folds purged, normalización per-fold, cuantiles) + [[project-silver-rework]]. |
| G | Baja | Positions live muestran `unrealized_pnl=0` (entry=precio actual por diseño del adapter — el P&L exacto vive en execution_orders). | Cosmético; itemización futura: reconstruir entries desde fills. |
| H | Baja | REJECTED no se persisten · trade $20 del 07-03 vive solo en DuckDB local · bindings IAP región/proyecto redundantes · `run.invoker` de la SA scheduler sobre dashboard (residuo del debug, posiblemente innecesario) · libgomp1 WSL · gap gobernanza LLM local ([[cost-gap-llm-ledger]]). | Backlog menor, sin riesgo operativo. |

## 3. Lo que se auditó y quedó LIMPIO ✅

- **Blindaje de secretos:** operativa solo en SM como `secret_key_ref`; RO-key separada para el
  servicio expuesto; one-liners `printf` sin contexto; deny duro de `secrets versions access/add`.
- **Gobernanza de costos:** gatekeeper pre-bash con cost-est inline (se bloqueó a sí mismo 2 veces
  en esta revisión — funciona) · línea diaria pre-autorizada con freno rc=2 verificado cross-entorno
  · ledgers al día (LLM julio $0.2274/$150 · GCP ~$9.79/$10).
- **Defensas de ejecución:** carrera 0379 (señal de saldo + sonda real) · pockets por quote ·
  fill asíncrono re-consultado · fee reserve · long-only estructural · kill switch no-liquidante.
- **Watchdog:** validado E2E con emails reales y comité de emergencia; cooldown atómico GCS.
- **Anti-injection de noticias:** DeBERTa activo; noticia inyectada marcada y excluida (validado F4).
- **Identidad estadística:** champion intacto sin tunear (banda anti-churn NO toca la señal, solo
  la ejecución); shadow persiste; protocolo v2 respetado en la propia auditoría de cadencia
  (cotas honestas, caveats registrados, juez = track record).

## 4. Estado del sistema al cierre

Cartera live ~$551 (5 posiciones + cash) · corrida diaria autónoma (3/3 días verificados) ·
watchdog cada 30 min → email · dashboard IAP con tile en vivo · 146 unit tests · CI verde ·
julio: LLM $0.23/$150, GCP $9.79/$10.

**El freno dijo "no" con dinero real en la mesa; el sistema compró cuando hubo señal, congeló
cuando no, y avisó por correo cuando cayó. Hermes hace lo que su documentación dice que hace —
que es la definición operativa de perfección que este proyecto persigue.**
