# agents:run — Dispara UNA corrida completa del pipeline multiagente

Ejecuta el ciclo completo: Gold → RegimeClassifier → Analysts → Debate → Trader → Risk →
Portfolio Manager → decisión. Registra transcripción y decisión. Requiere `cost:gate` LLM.

## Parámetros
`$ARGUMENTS` — modo override (opcional): `--dry-run` para simular sin consumir tokens reales.
Si vacío: corrida real con modelos configurados.

## Pasos

1. Verificar Gold válido: `/data:validate-gold`. Si inválido, abortar.

2. Leer ledger LLM para verificar presupuesto disponible.
   Si acumulado_mes >= $150: abortar con mensaje de pausa.

3. Llamar `/cost:gate` con:
   `llm: 1 corrida completa — ~$0.13 (free analysts) o ~$0.80 (modelos fuertes)`

4. Si autorizado: ejecutar pipeline:
   ```bash
   uv run python -m src.brain.pipeline --mode $HERMES_MODE $ARGUMENTS
   ```
   El pipeline retorna: `run_id`, `AgentDecision`, `RiskCheck`, `debate_transcript`.

5. Si `RiskCheck.approved=false`: registrar rechazo, NO ejecutar orden.
   Si `RiskCheck.approved=true` y no `--dry-run`: llamar `/execution:paper` o `/execution:live`
   según `EXCHANGE_MODE`.

6. Llamar `/cost:log` con:
   `llm|<fecha>|run_id <run_id>|<costo_real>|auto`

7. Mostrar resumen de la corrida:
   ```
   ── agents:run ── run_id: <uuid> ──────────────────────────
   Régimen    : BTC/USDT → trending (0.82) | ETH/USDT → volatile (0.71)
   Decisión   : BTC/USDT → BUY | $XX.XX (Kelly 0.25×)
   Risk check : ✅ aprobado | VaR 2σ: $X.XX
   Ejecutado  : ✅ paper order / ❌ rechazado por Risk
   Costo LLM  : $X.XX | Acumulado mes: $X.XX / $150.00
   ──────────────────────────────────────────────────────────
   ```

## Notas
- En `HERMES_MODE=local`, usa Ollama — más lento pero $0 de costo.
- El `run_id` es necesario para `/agents:debug`.
