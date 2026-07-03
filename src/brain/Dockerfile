# Hermes brain — Cloud Run (Fase 5). Build context = repo root:
#   docker build -f src/brain/Dockerfile -t hermes-brain .
FROM python:3.12-slim

# libgomp: OpenMP para LightGBM/sklearn
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock ./
# El brain necesita el extra news (sentence-transformers/UMAP/HDBSCAN/DeBERTa)
RUN uv sync --frozen --no-dev --no-install-project --extra news

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/app/.hf \
    TOKENIZERS_PARALLELISM=false

# Hornear los modelos en la imagen: sin descargas en el arranque frío diario.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')" && \
    python -c "from transformers import pipeline; pipeline('text-classification', model='protectai/deberta-v3-base-prompt-injection')"

COPY src/ ./src/
COPY scripts/ ./scripts/

EXPOSE 8080
CMD ["uvicorn", "src.brain.server:app", "--host", "0.0.0.0", "--port", "8080"]
