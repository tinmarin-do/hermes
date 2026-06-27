# test:integration — Tests de integración contra Binance testnet

## Parámetros
`$ARGUMENTS` — módulo específico (opcional). Ejemplo: `tests/integration/test_ccxt.py`

## Pasos

1. Verificar que `BINANCE_TESTNET_API_KEY` y `BINANCE_TESTNET_API_SECRET` están definidos.
   Si no: mostrar instrucciones para obtenerlos en testnet.binance.vision.

2. Ejecutar:
   ```bash
   EXCHANGE_MODE=testnet uv run pytest tests/integration/ -v --tb=short -m integration $ARGUMENTS
   ```

3. Tests incluyen:
   - Conexión a Binance testnet y fetch de OHLCV.
   - Ciclo completo Bronze → Silver → Gold con datos reales de testnet.
   - Paper order submission y verificación de fill.
   - Guardrails: verificar que orden fuera de whitelist es rechazada.

4. Mostrar resultados y tiempos de ejecución por test.

## Notas
- Pueden fallar por rate limiting de testnet — reintentar con `--timeout=60`.
- No consumen capital real ni LLM tokens.
