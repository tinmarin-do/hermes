# infra:state — Estado actual de Terraform (solo lectura)

Muestra el estado de los recursos gestionados por Terraform. No modifica nada.

## Parámetros
`$ARGUMENTS` — recurso específico (opcional). Ejemplo: `module.cloud_run.google_cloud_run_service.dashboard`
Si vacío, muestra listado completo.

## Pasos

1. Verificar `HERMES_MODE=cloud`.

2. Ejecutar:
   ```bash
   cd terraform
   terraform state list $ARGUMENTS
   ```
   Si `$ARGUMENTS` es un recurso específico:
   ```bash
   terraform state show $ARGUMENTS
   ```

3. Mostrar resultado formateado.

## Notas
- Solo lectura. Para modificar el estado manualmente, requiere intervención fuera del harness.
