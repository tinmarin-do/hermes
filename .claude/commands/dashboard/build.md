# dashboard:build — Genera assets del dashboard desde BD

Construye el snapshot del dashboard (curva de equity, posiciones, métricas de riesgo,
debate viewer) leyendo de la BD. No despliega — solo genera los datos.

## Parámetros
Ninguno.

## Pasos

1. Ejecutar builder:
   ```bash
   uv run python -m src.dashboard.build
   ```
   Genera:
   - Curva de equity (JSON para Chart.js).
   - Historial de trades con P&L.
   - Métricas ajustadas por riesgo: Sharpe + PSR, Sortino, max drawdown.
   - Posición actual + P&L no realizado.
   - Última transcripción de debate (para el debate viewer).
   - Panel MLOps: costo/corrida, latencia promedio, uptime.

2. Guardar snapshot en `src/dashboard/static/data/snapshot.json`.

3. Confirmar: `✅ Snapshot generado. Listo para servir o /dashboard:deploy.`

## Notas
- El dashboard lee del snapshot (costo por visitante = $0).
- El botón "correr ahora" llama `/agents:run` directamente — es el único path con costo variable.
