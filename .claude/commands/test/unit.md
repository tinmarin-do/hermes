# test:unit — Corre unit tests (sin dependencias externas)

## Parámetros
`$ARGUMENTS` — módulo específico (opcional). Ejemplo: `src/data/bronze`
Si vacío: todos los unit tests.

## Pasos

1. Ejecutar:
   ```bash
   uv run pytest tests/unit/ -v --tb=short -m unit $ARGUMENTS
   ```

2. Mostrar resultados con cobertura:
   ```bash
   uv run pytest tests/unit/ --cov=src --cov-report=term-missing -m unit
   ```

3. Si hay fallos: mostrar el traceback completo de cada test fallido.
   Sugerir comando exacto para re-correr solo el test fallido.

## Notas
- Unit tests no deben tocar BD, exchange, ni LLM — usar mocks.
- Bloqueante en CI para toda PR a `develop`.
