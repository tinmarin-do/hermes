# test:e2e — Pipeline completo end-to-end en paper mode

Corre el pipeline completo desde ingesta hasta orden paper, en local o testnet.
Es el test más costoso: **SIEMPRE invoca el LLM real** (DeepSeek), también en local.

## Parámetros
`$ARGUMENTS` — `--local` para forzar modo local aunque `HERMES_MODE=cloud`.

## Pasos

1. Verificar stack activo según modo:
   - `local`: `/infra:local-status` → si no corre, sugerir `/infra:local-up`.
   - `cloud`: `/ops:health`.

2. **Cotizar y gatear SIEMPRE** (regla #6 — nunca saltar `/cost:gate`, aunque el
   costo sea ~$0, sin importar el modo). Obtener el estimado data-driven sin invocar
   modelos y pasarlo a `/cost:gate`:
   ```bash
   EST=$(uv run python -m src.brain.runner --estimate)
   ```
   → `/cost:gate` con `llm: 1 corrida e2e — ~$<EST> USD (estimado por src.brain.cost_meter)`.
   Si no se autoriza, ABORTAR (no correr nada).

3. Si autorizado, ejecutar pipeline. El `-m e2e` es OBLIGATORIO: el default de pytest
   (`addopts`) deselecciona e2e/integration para que un `pytest` suelto no gaste LLM;
   `-m e2e` overridea ese filtro a propósito.
   ```bash
   uv run pytest tests/e2e/ -v --tb=short -m e2e $ARGUMENTS
   ```
   El e2e test verifica:
   - Bronze ingestado correctamente.
   - Silver features calculados.
   - Gold régimen clasificado.
   - Pipeline de agentes completado con decisión.
   - RiskCheck ejecutado (aprobado o rechazado correctamente).
   - Paper order registrada en BD.
   - Métricas registradas en ledger LLM.

4. Mostrar resultado: duración total, etapas completadas, decisión del pipeline.

5. **Loguear el costo REAL** (regla #5): la corrida queda en DuckDB `llm_cost_runs`
   con `logged_to_ledger=FALSE`. Tomar su `run_id` + costo medido y llamar `/cost:log`
   con `llm|<fecha>|run_id <id> (e2e test)|<costo_real>|auto`. Eso además flipea el flag.

## Notas
- SIEMPRE usa DeepSeek API (~$0.01/corrida) — por eso cotiza+gatea aunque sea barato.
- NUNCA correr `pytest tests/` para esto: el addopts lo deja en solo-unit. Usar `-m e2e`.
- Correr antes de toda PR a `main`.
