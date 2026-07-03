#!/usr/bin/env bash
# Corrida diaria de Hermes (cron) — ver scripts/daily_run.py
# crontab:  10 8 * * *  /home/tea/hermes/scripts/daily_run.sh
# Nota WSL: solo corre si la instancia WSL está viva a esa hora.
set -uo pipefail

REPO="/home/tea/hermes"
LOG="$REPO/data/daily_runs.log"
cd "$REPO"

# .env local (DeepSeek key etc.) — cron no hereda direnv
if [ -f "$REPO/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$REPO/.env"
  set +a
fi
export HERMES_MODE=local
export EXCHANGE_MODE=paper

{
  "$REPO/.venv/bin/python" -m scripts.daily_run
  echo "exit=$?"
} >> "$LOG" 2>&1
