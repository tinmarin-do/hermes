# backend.tf — NO commitear con valores reales.
# El bucket se crea en /infra:bootstrap antes del primer terraform init.
# Inicializar con:
#   terraform init \
#     -backend-config="bucket=$TF_STATE_BUCKET" \
#     -backend-config="prefix=hermes/state"

# Este archivo está intencionalmente vacío — la config se pasa por CLI.
# Ver scripts/infra-bootstrap.sh para el comando completo.
