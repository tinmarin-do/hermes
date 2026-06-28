# data:backfill — Relleno histórico para UN símbolo + rango específico

Orquesta ingesta Bronze + transformación Silver para un rango histórico completo.
Compuesto: llama `/data:ingest-bronze` → `/data:validate-bronze` → `/data:transform-silver`
→ `/data:validate-silver` en secuencia, con stop-on-error.

## Parámetros
`$ARGUMENTS` — formato: `<símbolo> <timeframe> <desde> <hasta>`
Ejemplo: `BTC/USDT 1h 2025-01-01 2026-06-01`

## Pasos

1. Parsear y validar rango. Si más de 365 días, advertir que puede tomar varios minutos.

2. Llamar `/data:ingest-bronze <símbolo> <timeframe> <desde> <hasta>`.
   Si falla: abortar con detalle del error.

3. Llamar `/data:validate-bronze <símbolo> <timeframe>`.
   Si inválido: abortar.

4. Llamar `/data:transform-silver <símbolo> <timeframe>`.
   Si falla: abortar.

5. Llamar `/data:validate-silver <símbolo> <timeframe>`.

6. Reportar: registros Bronze + Silver producidos, rango cubierto, duración total.

## Notas
- No procesa Gold — ese paso se hace bajo demanda con `/data:aggregate-gold`.
- ccxt limita peticiones por minuto — backfills largos incluyen delays automáticos.
