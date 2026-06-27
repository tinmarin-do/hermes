# infra:plan — Terraform plan (solo lectura)

Ejecuta `terraform plan` y muestra los cambios propuestos. No modifica nada, no requiere
`cost:gate`. Usar siempre antes de `/infra:apply`.

## Parámetros
`$ARGUMENTS` — módulo o target específico (opcional). Ejemplo: `module.cloud_run`
Si vacío, planifica todo.

## Pasos

1. Verificar que `HERMES_MODE=cloud`. Si es `local`, abortar.

2. Cambiar al directorio `terraform/`.

3. Ejecutar:
   ```bash
   terraform init -reconfigure
   terraform plan -out=tfplan.binary $ARGUMENTS
   terraform show -no-color tfplan.binary
   ```

4. Mostrar el resumen de cambios (recursos a crear, modificar, destruir).

5. Si hay recursos a **destruir**: resaltar con `⚠️ DESTRUCCIÓN` y recomendar revisar
   antes de `/infra:apply`.

6. Guardar `tfplan.binary` para uso de `/infra:apply`.

## Notas
- No llama `cost:gate` — es operación de solo lectura.
- El plan generado es válido por la sesión actual. Regenerar si hay cambios en el entorno.
