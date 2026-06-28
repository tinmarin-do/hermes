# hermes:run — Orquestador lean del pipeline completo

El orquestador no tiene lógica propia. Su única responsabilidad es encadenar los skills
en el orden correcto y detenerse en el primero que falle.

## Parámetros
`$ARGUMENTS`:
- vacío → corrida estándar (paper/testnet según EXCHANGE_MODE)
- `--local` → fuerza HERMES_MODE=local (DeepSeek API + DuckDB + paper)
- `--dry-run` → ejecuta todo hasta agents:run pero sin orden

## Flujo

```
/ops:health
    ↓ (si falla: abortar)
/data:aggregate-gold [$SYMBOLS]
    ↓ (si falla: abortar)
/data:validate-gold
    ↓ (si inválido: abortar)
/agents:run [$ARGUMENTS]
    ↓ (si Risk rechaza: registrar y terminar — no es error)
/execution:paper | /execution:live
    ↓
/execution:status
    ↓
/cost:status
```

## Pasos

1. Llamar `/ops:health`. Si algún servicio no está saludable: abortar con detalle.

2. Llamar `/data:aggregate-gold`. Si falla: abortar.

3. Llamar `/data:validate-gold`. Si inválido o antiguo: abortar.

4. Llamar `/agents:run $ARGUMENTS`.
   - Si `RiskCheck.approved=false`: registrar decisión, mostrar razón, terminar sin error.
   - Si `status=blocked` (cap LLM): terminar, no reintentar.

5. Si aprobado y no `--dry-run`:
   - `EXCHANGE_MODE=paper|testnet` → `/execution:paper`
   - `EXCHANGE_MODE=live` → `/execution:live` (con su confirmación doble propia)

6. Llamar `/execution:status` para mostrar estado actualizado del portafolio.

7. Llamar `/cost:status` para mostrar gasto acumulado.

## Salida esperada
```
── hermes:run ── pipeline completo ───────────────────────
[1/7] ops:health       ✅
[2/7] data:gold        ✅ BTC/USDT trending | ETH/USDT volatile
[3/7] data:validate    ✅
[4/7] agents:run       ✅ BUY BTC/USDT $12.50 (conf: 72%)
[5/7] risk:check       ✅ aprobado
[6/7] execution        ✅ paper order ejecutada
[7/7] status           ✅ P&L día: +$0.23 | LLM: $0.13 / $150.00
──────────────────────────────────────────────────────────
```

## Notas
- Este skill NO toma decisiones — delega todo a los skills atómicos.
- Ante cualquier falla, reportar el skill exacto que falló y el mensaje de error.
- Para debug de una corrida específica: `/agents:debug <run_id>`.
