# data:validate-silver — Valida la capa Silver para UN símbolo

Verifica que los features de régimen fueron calculados correctamente.

## Parámetros
`$ARGUMENTS` — formato: `<símbolo> <timeframe>`

## Pasos

1. Ejecutar validaciones:
   ```bash
   uv run python -m src.data.silver.validate --symbol "$SYMBOL" --timeframe "$TF"
   ```
   Checks:
   - Hurst exponent en rango (0, 1). Valor típico BTC: 0.45–0.55.
   - Volatilidad GARCH > 0 y < 5 (cripto puede ser alta pero no infinita).
   - Spread estimado > 0.
   - Sin NaN en columnas de features.
   - Cobertura: al menos 95% de registros Bronze tienen contraparte Silver.

2. Mostrar reporte con distribución de regímenes detectados:
   ```
   Hurst < 0.45 (mean-reverting): XX%
   Hurst 0.45–0.55 (random walk): XX%
   Hurst > 0.55 (trending)      : XX%
   ```
