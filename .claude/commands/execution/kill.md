# execution:kill — Kill switch: cierra/pausa todo inmediatamente

Activa el kill switch: cierra todas las posiciones abiertas al mercado y pausa el pipeline
de agentes. Acción de emergencia — no requiere `cost:gate` por ser operación de seguridad.

## Parámetros
`$ARGUMENTS` — `--pause-only` para solo pausar sin cerrar posiciones (opcional).

## Pasos

1. Confirmar acción:
   ```
   ⛔ KILL SWITCH
   Posiciones a cerrar : X (ver /execution:status)
   Modo               : cerrar todo + pausar  /  --pause-only
   Escribe "KILL" para confirmar.
   ```

2. Esperar confirmación literal `KILL`. Si no: abortar.

3. Si no `--pause-only`: ejecutar cierre de mercado para cada posición abierta.
   ```bash
   uv run python -m src.execution.kill --close-all
   ```

4. Pausar Cloud Scheduler (si `HERMES_MODE=cloud`):
   ```bash
   gcloud scheduler jobs pause hermes-pipeline --location=$GCP_REGION
   ```
   (A través de `/infra:gcloud` para mantener el log.)

5. Marcar `kill_switch=true` en BD.

6. Enviar notificación (log estructurado con nivel CRITICAL).

7. Confirmar: `✅ Kill switch activado. Pipeline pausado. Posiciones cerradas.`

## Notas
- Para reactivar: corregir la causa raíz, luego actualizar `kill_switch=false` en BD y
  reactivar Cloud Scheduler manualmente con `/infra:gcloud`.
