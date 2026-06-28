# Hermes dashboard — build context is the repo root (see docker-compose*.yml).
#   docker build -f src/dashboard/Dockerfile -t hermes-dashboard .
FROM python:3.12-slim

WORKDIR /app

# Install deps from the lockfile first (cached layer).
RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# App source — `src` is importable from /app (packages = ["src"]).
COPY src/ ./src/

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    HERMES_MODE=local

EXPOSE 8080
CMD ["uvicorn", "src.dashboard.app:app", "--host", "0.0.0.0", "--port", "8080"]
