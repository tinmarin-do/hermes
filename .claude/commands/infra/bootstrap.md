# infra:bootstrap — Bootstrap GCP desde cero

Crea el bucket de estado Terraform y habilita las APIs de GCP necesarias.
Es el primer skill a ejecutar en un proyecto GCP nuevo. Requiere `gcloud auth login` previo.

## Parámetros
Ninguno. Lee `GCP_PROJECT_ID`, `GCP_REGION`, `TF_STATE_BUCKET` del entorno.

## Pasos

1. Verificar que `HERMES_MODE=cloud`. Si es `local`, abortar con mensaje claro.

2. Verificar que `GCP_PROJECT_ID` y `TF_STATE_BUCKET` estén definidos en el entorno.

3. Llamar `/cost:quote` con:
   `gcp: bootstrap — bucket tfstate <TF_STATE_BUCKET> (<GCP_REGION>, versioning) + habilitación de APIs`

4. Llamar `/cost:gate` para autorización explícita. Si se rechaza, abortar.

5. Ejecutar bootstrap vía `/infra:gcloud` para cada operación atómica:
   a. Crear bucket tfstate con versioning habilitado.
   b. Habilitar APIs requeridas:
      - `run.googleapis.com`
      - `sqladmin.googleapis.com`
      - `cloudscheduler.googleapis.com`
      - `secretmanager.googleapis.com`
      - `artifactregistry.googleapis.com`
      - `iam.googleapis.com`
      - `logging.googleapis.com`
      - `monitoring.googleapis.com`

6. Verificar que el bucket existe y las APIs están habilitadas.

7. Confirmar: `✅ infra:bootstrap completo. Puedes ejecutar /infra:apply ahora.`

## Notas
- Requiere rol `roles/owner` o `roles/editor` en el proyecto GCP.
- El bucket tfstate tiene versioning — no se puede accidentalmente perder el estado.
