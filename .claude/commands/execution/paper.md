# execution:paper — Envía UNA orden a paper/testnet

Ejecuta una orden simulada (paper) o contra Binance testnet. Requiere `RiskCheck` aprobado.

## Parámetros
`$ARGUMENTS` — formato: `<símbolo> <side> <size_usd> <run_id>`
Ejemplo: `BTC/USDT buy 12.50 3f7a2b1c`

## Pasos

1. Verificar que `EXCHANGE_MODE=paper` o `EXCHANGE_MODE=testnet`.
   Si `EXCHANGE_MODE=live`: redirigir a `/execution:live`.

2. Verificar que existe `RiskCheck.approved=true` para el `run_id`.

3. Aplicar guardrails:
   - Verificar símbolo en whitelist.
   - Verificar que `size_usd` <= Kelly calculado para el `run_id`.
   - Verificar posiciones abiertas <= `HERMES_MAX_POSITIONS`.
   - Verificar pérdida diaria acumulada no excede límite.

4. Ejecutar orden:
   ```bash
   uv run python -m src.execution.cli \
     --mode "$EXCHANGE_MODE" \
     --symbol "$SYMBOL" --side "$SIDE" --size-usd "$SIZE_USD" \
     --run-id "$RUN_ID"
   ```

5. Registrar en BD: orden, fill price simulado, slippage estimado.

6. Confirmar: `✅ Orden paper ejecutada: <detalles>`.
