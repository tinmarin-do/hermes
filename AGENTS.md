# Hermes — Agent Interoperability Contract

**Version:** 0.3.0  
**Project:** Hermes — Multi-agent AI trading system  
**Contract type:** Custom JSON Schema (provider-agnostic)

Any agent (Claude, GPT, Gemini, LangGraph node, or other) that needs to interact with
Hermes tools must follow this contract. Tool definitions live in `.agents/tools/`.

---

## Agent Roles

| Role | Responsibility | Primary tools |
|------|---------------|---------------|
| `orchestrator` | Coordinates the full pipeline run | `agents.*`, `cost.*` |
| `data-agent` | Manages medallion data pipeline | `data.*` |
| `trading-agent` | Analyst, trader, portfolio manager | `execution.*`, `agents.*` |
| `risk-agent` | Pre-trade risk validation | `execution.*` |

Full role definitions: `.agents/roles/`

---

## Tool Invocation Protocol

All tools follow this request/response schema:

### Request
```json
{
  "tool": "<namespace>.<action>",
  "args": { },
  "context": {
    "agent_role": "<role>",
    "hermes_mode": "local | cloud",
    "run_id": "<uuid | null>"
  }
}
```

### Response
```json
{
  "tool": "<namespace>.<action>",
  "status": "ok | error | blocked",
  "data": { },
  "cost_incurred": 0.00,
  "message": "<human-readable result>"
}
```

`status: blocked` means cost:gate rejected the operation — do NOT retry without user authorization.

---

## Tool Namespaces

- [`cost`](.agents/tools/cost.json) — Cost estimation and authorization gate
- [`data`](.agents/tools/data.json) — Medallion data pipeline (Bronze/Silver/Gold)
- [`agents`](.agents/tools/agents.json) — Multi-agent pipeline execution
- [`execution`](.agents/tools/execution.json) — Order execution and positions
- [`infra`](.agents/tools/infra.json) — Infrastructure provisioning
- [`ops`](.agents/tools/ops.json) — Operations and observability

---

## Data Schemas

### MarketData (Bronze)
```json
{
  "symbol": "BTC/USDT",
  "exchange": "binance",
  "timeframe": "1h",
  "timestamp": "2026-06-26T00:00:00Z",
  "open": 0.0,
  "high": 0.0,
  "low": 0.0,
  "close": 0.0,
  "volume": 0.0
}
```

### RegimeSignal (Gold)
```json
{
  "symbol": "BTC/USDT",
  "timestamp": "2026-06-26T00:00:00Z",
  "regime": "trending | mean-reverting | volatile | illiquid",
  "hurst_exponent": 0.0,
  "garch_volatility": 0.0,
  "bid_ask_spread": 0.0,
  "confidence": 0.0
}
```

### AgentDecision
```json
{
  "run_id": "<uuid>",
  "timestamp": "2026-06-26T00:00:00Z",
  "symbol": "BTC/USDT",
  "action": "buy | sell | hold | short",
  "confidence": 0.0,
  "kelly_fraction": 0.0,
  "position_size_usd": 0.0,
  "rationale": "<debate summary>",
  "debate_transcript": "<full LangGraph transcript>"
}
```

> `action: short` solo es válido bajo la política ultra-conservadora (`P ≤ 0.25` +
> confianza ≥ 0.50 + régimen bajista; cap 10%). Short real requiere venue de futuros;
> en spot/live arranca deshabilitado. Ver `docs/DESIGN_portfolio_allocator.md`.

### PortfolioAllocation (vector — diseño, pendiente de implementación)
Reemplaza la decisión única por un **vector de pesos** sobre los símbolos permitidos,
rebalanceado a diario. Cada `leg` es una `AgentDecision` derivada del delta vs el libro actual.

```json
{
  "run_id": "<uuid>",
  "timestamp": "2026-06-26T00:00:00Z",
  "budget_usd": 1.0,
  "weighting": "conf_x_inverse_vol",
  "legs": [
    { "symbol": "BTC/USDT", "target_weight": 0.0, "action": "buy | sell | hold | short", "position_size_usd": 0.0 }
  ],
  "cash_usd": 0.0,
  "short_exposure_usd": 0.0
}
```

### RiskCheck
```json
{
  "run_id": "<uuid>",
  "approved": true,
  "var_2sigma": 0.0,
  "correlation_with_open": 0.0,
  "daily_loss_remaining": 0.0,
  "kelly_size": 0.0,
  "short_exposure_pct": 0.0,
  "short_stop_loss": null,
  "rejection_reason": null
}
```

> Para legs `short`, el comité de riesgo aplica política estricta: `short_exposure_pct ≤ 10%`
> del budget, `short_stop_loss` obligatorio, veto si la confianza es baja, y rechazo de shorts
> correlacionados entre sí.

---

## Guardrails (non-negotiable)

Agents MUST respect these limits. The risk-agent enforces them pre-trade.

| Guardrail | Rule |
|-----------|------|
| Position sizing | Kelly 0.10× based on PM confidence (calibrated 2026-07-03) |
| VaR pre-trade | Reject if 2σ loss > daily limit |
| Correlation cap | Reject if corr > 0.7 AND total exposure > limit |
| Daily loss limit | Halt trading for the day when reached |
| Symbol whitelist | Only approved symbols (see `.env` HERMES_ALLOWED_SYMBOLS) |
| Max open positions | See `.env` HERMES_MAX_POSITIONS |
| **Short policy** | Origina solo si `P ≤ 0.25` + conf ≥ 0.50 + régimen bajista; **exposición corta ≤ 10%** del budget; stop-loss obligatorio; **futuros-only** (spot no puede); **OFF por default en live** |
| **Portfolio budget** | Reparto entre símbolos por `conf × inverse-vol`; **$1 paper (local) / $400 cloud** (decisión 2026-07-03); rebalanceo diario por delta vs libro |

---

## Mode Switching

Agents detect the active mode from environment or context:

| Variable | Local mode | Cloud mode |
|----------|-----------|------------|
| `HERMES_MODE` | `local` | `cloud` |
| LLM endpoint | API key from Secret Manager | API key from Secret Manager |
| Database | DuckDB file at `data/hermes.duckdb` | Cloud SQL connection string |
| Exchange | Paper adapter | Binance testnet/live |

---

## Calibration

The risk guardrails are periodically calibrated via `src/brain/calibrate.py`:

- **Phase 1 — Quantitative backtest:** 126 weekly points over ~2.5 years, heuristic signals
  (regime → filter → action), grid search over Kelly fraction and loss limit. No LLM cost.
- **Phase 2 — LLM validation:** Top 20 most volatile dates run through the full LangGraph
  pipeline with reduced debate rounds. Compares LLM decisions vs quantitative model.
- **Output:** `docs/calibration_report.md` with optimal params and metrics.
- **Run:** `direnv exec . .venv/bin/python -m src.brain.calibrate --concurrency 3 --debate-rounds 1`

Current calibrated values (`docs/calibration_report.md`, 2026-07-03): Kelly 0.10,
daily loss limit 0.04, F1 = 70.8%. Deployed as `HERMES_KELLY_FRACTION` /
`HERMES_DAILY_LOSS_LIMIT_PCT` (see `.env.example`).

---

## Constraints for External Agents

1. Never call `execution.live` without a passing `RiskCheck`.
2. Never bypass `cost.gate` for any GCP or LLM operation.
3. Never write to `docs/cost_ledger_*.md` directly — always via `cost.log` tool.
4. Always include `run_id` in context when operating within a pipeline run.
5. `status: blocked` is final — escalate to human operator.
