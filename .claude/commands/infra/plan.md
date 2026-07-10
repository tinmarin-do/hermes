# infra:plan — Terraform plan (solo lectura)

Ejecuta `terraform plan` y muestra los cambios propuestos. No modifica nada, no requiere
`cost:gate`. Usar siempre antes de `/infra:apply`.

## Parámetros
`$ARGUMENTS` — módulo o target específico (opcional). Ejemplo: `module.cloud_run`
Si vacío, planifica todo.

## Pasos

1. Verificar que `HERMES_MODE=cloud`. Si es `local`, abortar.

2. Cambiar al directorio `terraform/`.

3. Cargar variables desde `.env` (una shell sin direnv activo NO las trae solas —
   el `dotenv` del final de `.envrc` no corre fuera de direnv, y el orden de
   ese archivo evalúa `TF_VAR_project_id="$GCP_PROJECT_ID"` ANTES de cargar
   `.env`, así que un `source .envrc` a secas también deja `TF_VAR_project_id`
   vacío — hallazgo 2026-07-10, ver `terraform/backend.tf`):
   ```bash
   set -a; source ../.env 2>/dev/null; set +a
   export TF_VAR_project_id="$GCP_PROJECT_ID"
   export TF_VAR_region="$GCP_REGION"
   ```

4. Ejecutar (el backend GCS es parcial en `main.tf` — el bucket/prefix se
   pasan por CLI, NUNCA hardcodeados en `.tf`, ver `terraform/backend.tf`;
   sin estos flags `terraform init` pregunta el bucket interactivamente y
   **crashea** en una sesión no interactiva — hallazgo 2026-07-10):
   ```bash
   terraform init -reconfigure \
     -backend-config="bucket=$TF_STATE_BUCKET" \
     -backend-config="prefix=hermes/state"
   terraform plan -out=tfplan.binary $ARGUMENTS
   terraform show -no-color tfplan.binary
   ```

5. Mostrar el resumen de cambios (recursos a crear, modificar, destruir).

6. Si hay recursos a **destruir**: resaltar con `⚠️ DESTRUCCIÓN` y recomendar revisar
   antes de `/infra:apply`.

7. Guardar `tfplan.binary` para uso de `/infra:apply`.

## Notas
- No llama `cost:gate` — es operación de solo lectura.
- El plan generado es válido por la sesión actual. Regenerar si hay cambios en el entorno.
