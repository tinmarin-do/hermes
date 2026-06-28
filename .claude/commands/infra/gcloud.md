# infra:gcloud — Ad-hoc gcloud CLI con cotización y gate

Ejecuta UN comando `gcloud` o `gsutil` con autorización explícita previa, siguiendo el
patrón `gcloud ad-hoc`: cotización con `/cost:quote` → gate con `/cost:gate` → log con `/cost:log`.

## Parámetros
`$ARGUMENTS` — el comando completo a ejecutar (sin el prefijo `gcloud`). Ejemplos:
- `iam service-accounts create hermes-worker --display-name="Hermes Worker"`
- `projects add-iam-policy-binding $GCP_PROJECT_ID --member=... --role=...`
- `run jobs deploy hermes-brain --image=... --region=$GCP_REGION`

## Pasos

1. Verificar que `HERMES_MODE=cloud`. Si es `local`, abortar.

2. Mostrar el comando completo que se ejecutará:
   ```
   Comando a ejecutar: gcloud $ARGUMENTS
   ```

3. Determinar si el comando tiene costo (mayoría son $0.00 para operaciones de config).
   Llamar `/cost:quote` con: `gcp: gcloud $ARGUMENTS`

4. Llamar `/cost:gate` para autorización explícita.

5. Si autorizado: ejecutar `gcloud $ARGUMENTS` y capturar output.

6. Llamar `/cost:log` con:
   `gcp|<fecha>|gcloud ad-hoc: $ARGUMENTS|<costo>|usuario`

7. Mostrar output del comando y confirmar.

## Notas
- Para comandos gsutil/bq, adaptar el prefijo pero mantener el mismo flujo de gate.
- Operaciones de retiro/billing/project-delete requieren confirmación doble.
