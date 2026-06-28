# data:transform-silver — Limpia y computa features de régimen para UN símbolo

Toma datos Bronze validados y produce la capa Silver: datos limpios + features de régimen
(Hurst exponent, GARCH volatility, bid-ask spread estimado). Una invocación = un símbolo.

## Parámetros
`$ARGUMENTS` — formato: `<símbolo> <timeframe>`
Ejemplo: `BTC/USDT 1h`

## Pasos

1. Verificar que Bronze existe y está validado para el símbolo. Si no, sugerir
   `/data:ingest-bronze` + `/data:validate-bronze` primero.

2. Ejecutar transformación:
   ```bash
   uv run python -m src.data.silver.transform --symbol "$SYMBOL" --timeframe "$TF"
   ```
   Pipeline:
   - Limpieza: rellenar gaps menores con interpolación lineal, eliminar outliers (> 5σ).
   - Hurst exponent: ventana deslizante de 100 velas.
   - GARCH(1,1): volatilidad estimada con `arch` library.
   - Spread estimado: `(high - low) / close` como proxy de liquidez.
   - Retornos log y volatilidad realizada.

3. Reportar: registros producidos, distribución de Hurst (trending/mean-reverting/random),
   rango de volatilidad GARCH.

4. Recomendar `/data:validate-silver` como siguiente paso.

## Notas
- Silver NO contiene señales de trading — solo features estadísticos del mercado.
- El Hurst exponent requiere mínimo 100 observaciones para ser estable.
