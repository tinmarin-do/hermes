# data:aggregate-gold — Produce señales Gold listas para los agentes

Toma Silver y produce la capa Gold: régimen clasificado + señales agregadas listas para
consumo del pipeline multiagente. Una invocación produce el snapshot Gold más reciente.

## Parámetros
`$ARGUMENTS` — lista de símbolos separados por coma (opcional).
Ejemplo: `BTC/USDT,ETH/USDT`
Si vacío: procesa todos los símbolos en `HERMES_ALLOWED_SYMBOLS`.

## Pasos

1. Para cada símbolo:
   ```bash
   uv run python -m src.data.gold.aggregate --symbol "$SYMBOL"
   ```
   Pipeline:
   - RegimeClassifier: combina Hurst + GARCH + spread → clase `trending | mean-reverting | volatile | illiquid`.
   - Confianza del régimen: probabilidad de la clase dominante.
   - Señales técnicas contextuales (condicionadas al régimen).
   - Snapshot JSON con schema `RegimeSignal` del contrato de agentes.

2. Persistir snapshot Gold en BD (tabla `gold_signals`).

3. Reportar: régimen actual por símbolo + confianza.

4. Recomendar `/data:validate-gold` como siguiente paso.

## Notas
- Gold es el único input que reciben los agentes LLM — nada de Bronze o Silver crudo.
- El snapshot es point-in-time; caducan con la siguiente corrida.
