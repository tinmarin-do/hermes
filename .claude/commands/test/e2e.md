# test:e2e — Pipeline completo end-to-end en paper mode

Corre el pipeline completo desde ingesta hasta orden paper, en local o testnet.
Es el test más costoso (puede invocar LLM en cloud mode).

## Parámetros
`$ARGUMENTS` — `--local` para forzar Ollama aunque `HERMES_MODE=cloud`.

## Pasos

1. Verificar stack activo según modo:
   - `local`: `/infra:local-status` → si no corre, sugerir `/infra:local-up`.
   - `cloud`: `/ops:health`.

2. Si `HERMES_MODE=cloud` y no `--local`:
   Llamar `/cost:gate` con `llm: 1 corrida e2e — ~$0.13`.

3. Ejecutar pipeline completo:
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

## Notas
- Con `--local` usa Ollama — más lento (minutos) pero gratis.
- Correr antes de toda PR a `main`.
