# execution:status — Posiciones abiertas + P&L actual

Muestra el estado actual del portafolio: posiciones, P&L realizado y no realizado,
exposición total y distancia al kill switch.

## Parámetros
Ninguno.

## Pasos

1. Consultar BD para posiciones abiertas y trades del día.

2. Si `EXCHANGE_MODE=live|testnet`: obtener precios actuales de Binance para P&L no realizado.

3. Calcular métricas de riesgo en tiempo real:
   - P&L no realizado por posición.
   - Pérdida diaria acumulada vs límite (`HERMES_DAILY_LOSS_LIMIT_PCT`).
   - Exposición total vs capital.

4. Mostrar:
   ```
   ── execution:status ──────────────────────────────────────
   Posiciones abiertas: X / $HERMES_MAX_POSITIONS

   BTC/USDT  LONG  $12.50  entry: $65,000  now: $66,200  P&L: +$0.23 (+1.84%)
   ETH/USDT  —     (sin posición)

   P&L día   : +$0.23
   Límite día : $10.00 (2% de $500) — XX% usado
   Kill switch: INACTIVO ✅
   ──────────────────────────────────────────────────────────
   ```

5. Si pérdida diaria >= 90% del límite: mostrar alerta ⚠️ y sugerir `/execution:kill`.
