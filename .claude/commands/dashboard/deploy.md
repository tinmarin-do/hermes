# dashboard:deploy — Despliega el dashboard a Cloud Run

Build de imagen Docker + push a Artifact Registry + deploy a Cloud Run.
Requiere `cost:gate`.

## Parámetros
`$ARGUMENTS` — tag de imagen (opcional). Default: `latest`.

## Pasos

1. Verificar `HERMES_MODE=cloud`.

2. Llamar `/cost:quote` con:
   `gcp: Cloud Run deploy hermes-dashboard (1vCPU 256MB, min-instances=0, max-instances=2)`

3. Llamar `/cost:gate`. Si rechaza: abortar.

4. Build y push:
   ```bash
   gcloud builds submit --tag gcr.io/$GCP_PROJECT_ID/hermes-dashboard:$TAG src/dashboard/
   ```
   (Vía `/infra:gcloud`.)

5. Deploy a Cloud Run:
   ```bash
   gcloud run deploy hermes-dashboard \
     --image gcr.io/$GCP_PROJECT_ID/hermes-dashboard:$TAG \
     --region $GCP_REGION \
     --allow-unauthenticated \
     --min-instances 0 --max-instances 2
   ```

6. Llamar `/cost:log` con costo estimado.

7. Mostrar URL pública del dashboard.
