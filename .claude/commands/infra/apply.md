# infra:apply — Terraform apply con gate de costo

Aplica el plan de Terraform previamente generado. Requiere `cost:gate` y que `/infra:plan`
haya sido ejecutado en la misma sesión.

## Parámetros
`$ARGUMENTS` — descripción de qué se está aplicando (para el ledger). Ejemplo:
`módulos cloud-run + cloud-sql, primera vez`

## Pasos

1. Verificar que `HERMES_MODE=cloud`. Si es `local`, abortar.

2. Verificar que `terraform/tfplan.binary` existe. Si no, pedir ejecutar `/infra:plan` primero.

3. Leer el plan para extraer recursos a crear/modificar y estimar costo mensual.

4. Llamar `/cost:gate` con:
   `gcp: terraform apply — <$ARGUMENTS> — <resumen de recursos>`

5. Si el gate rechaza: abortar. Si autoriza: continuar.

6. Ejecutar:
   ```bash
   cd terraform && terraform apply tfplan.binary
   ```

7. Capturar outputs relevantes (URLs de Cloud Run, connection strings, etc.).

8. Llamar `/cost:log` con:
   `gcp|<fecha>|terraform apply: <$ARGUMENTS>|<costo_estimado>|usuario`

9. Mostrar outputs y confirmar: `✅ infra:apply completado.`

## Notas
- NUNCA ejecutar sin `/infra:plan` previo en la misma sesión.
- Si el apply falla a medias, ejecutar `/infra:state` para inspeccionar antes de reintentar.
