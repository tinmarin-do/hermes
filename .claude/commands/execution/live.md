# execution:live — Envía UNA orden live a Binance (confirmación doble)

Ejecuta una orden real con capital real. Requiere `RiskCheck` aprobado, guardrails activos
y confirmación explícita doble del usuario.

## Parámetros
`$ARGUMENTS` — formato: `<símbolo> <side> <size_usd> <run_id>`

## Pasos

1. Verificar `EXCHANGE_MODE=live`. Si no, abortar.

2. Verificar `BINANCE_API_KEY` y `BINANCE_API_SECRET` definidos y con permisos solo-trade
   (sin retiro). Si se detecta permiso de retiro: ABORTAR con alerta crítica.

3. Verificar `RiskCheck.approved=true` para el `run_id`.

4. Verificar TODOS los guardrails (mismo que `/execution:paper` paso 3).

5. Mostrar confirmación doble:
   ```
   ⚠️  ORDEN LIVE — CAPITAL REAL
   Símbolo : <símbolo>
   Lado    : <BUY|SELL>
   Monto   : $<size_usd> USD
   Guardrails: ✅ Kelly ✅ VaR ✅ Correlación ✅ Daily limit
   Escribe "CONFIRMAR LIVE" para ejecutar.
   ```

6. Esperar confirmación literal `CONFIRMAR LIVE`. Si no coincide: abortar.

7. Ejecutar con adapter live de ccxt.

8. Registrar en BD: orden real, fill price, fees, slippage real.

9. Actualizar posición abierta y P&L.

## Notas
- Las API keys NUNCA deben tener permiso de retiro/withdrawal.
- Revisar `HERMES_CAPITAL_USD` antes de cada sesión live.
