"""Arquitectura medallón sobre noticias de mercado cripto.

Bronze (crudo intacto) → Silver (contrato Pydantic + cuarentena + MERGE idempotente)
→ Gold (embeddings + índice FAISS + búsqueda semántica).

Paquete autocontenido: sus únicas dependencias son las de `requirements.txt`
y escribe en su propia base DuckDB (`data/medallion.duckdb`).
"""
