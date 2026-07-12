# Hermes Lab — imagen del Cloud Run Job hermes-lab (arcos H11/H12).
# SIN extra news (sentence-transformers etc.); el extra nn trae torch CPU
# (index pytorch-cpu pineado en pyproject — sin wheels CUDA) para la fase NN §7.
# Build context = repo root:
#   gcloud builds submit --config src/lab/cloudbuild.yaml
FROM python:3.12-slim

# libgomp: OpenMP para LightGBM/sklearn
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --extra lab --extra nn

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

COPY src/ ./src/

# El job sobreescribe args por ejecución: p.ej. ["src.lab.experiment","--spec",URI]
ENTRYPOINT ["python", "-m"]
CMD ["src.lab.experiment", "--selftest"]
