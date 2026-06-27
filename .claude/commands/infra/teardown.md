# infra:teardown — Destruye recursos GCP (con gate doble)

Destruye recursos de Terraform. Operación destructiva e irreversible — requiere doble
confirmación y `cost:gate`.

## Parámetros
`$ARGUMENTS` — scope de destrucción: `all` o nombre de módulo específico.
Ejemplo: `module.cloud_run` o `all`

## Pasos

1. Verificar `HERMES_MODE=cloud`.

2. Si `$ARGUMENTS=all`: mostrar advertencia severa:
   ```
   ⛔ ADVERTENCIA: Esto destruirá TODA la infraestructura de Hermes en GCP.
   Los datos en Cloud SQL se perderán si no hay backup.
   Escribe "DESTRUIR TODO" para confirmar.
   ```
   Esperar confirmación literal. Si no coincide exactamente, abortar.

3. Ejecutar `/infra:plan` con `-destroy` para mostrar qué se destruirá.

4. Llamar `/cost:gate` con descripción explícita de lo que se destruye.

5. Si autorizado: ejecutar `terraform destroy -auto-approve` (o target específico).

6. Llamar `/cost:log` registrando la operación de teardown.

7. Confirmar recursos destruidos.

## Notas
- La base de datos Cloud SQL NO tiene backup automático en MVP — tomar snapshot manual antes.
- Preferir teardown de módulos individuales sobre `all` en la mayoría de los casos.
