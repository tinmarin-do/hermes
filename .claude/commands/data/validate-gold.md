# data:validate-gold — Valida la capa Gold

Verifica que el snapshot Gold está completo y listo para alimentar a los agentes.

## Parámetros
Ninguno. Valida el snapshot Gold más reciente.

## Pasos

1. Ejecutar:
   ```bash
   uv run python -m src.data.gold.validate
   ```
   Checks:
   - Existe snapshot reciente (< 2 horas de antigüedad).
   - Todos los símbolos en `HERMES_ALLOWED_SYMBOLS` tienen entrada.
   - `regime` es uno de los valores válidos.
   - `confidence` en [0, 1].
   - `hurst_exponent`, `garch_volatility`, `bid_ask_spread` presentes y en rangos válidos.
   - Schema exactamente igual al `RegimeSignal` de `AGENTS.md`.

2. Mostrar estado de cada símbolo:
   ```
   BTC/USDT : ✅ trending (conf: 0.82) — snapshot hace 47 min
   ETH/USDT : ✅ volatile (conf: 0.71) — snapshot hace 47 min
   ```

3. Si inválido o antiguo: recomendar `/data:aggregate-gold`.
