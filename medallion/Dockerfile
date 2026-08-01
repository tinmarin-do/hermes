# Imagen del medallón — contexto de build = esta carpeta (./medallion).
FROM python:3.12-slim

WORKDIR /app

# torch CPU explícito: sin esto pip baja la build CUDA (~2.5 GB) que no usamos.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./medallion/

# Corre como uid 1000 para que lo escrito en el volumen quede del usuario del
# host, no de root (si no, `data/` se vuelve intocable desde afuera).
# El cache de HF se pre-crea con dueño appuser: docker hereda ese ownership al
# inicializar el volumen nombrado (si no, lo crea como root y truena).
RUN useradd -u 1000 -m appuser \
 && mkdir -p /app/data /home/appuser/.cache/huggingface \
 && chown -R appuser /app /home/appuser
USER appuser

ENV PYTHONUNBUFFERED=1 \
    HOME=/home/appuser \
    MEDALLION_DUCKDB_PATH=/app/data/medallion.duckdb \
    MEDALLION_DATA_DIR=/app/data/medallion

CMD ["python", "-m", "medallion", "run"]
