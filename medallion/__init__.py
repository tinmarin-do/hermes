"""Arquitectura medallón autocontenida (entregable diplomado).

Bronze (crudo intacto) → Silver (contrato Pydantic + cuarentena + MERGE idempotente)
→ Gold (embeddings + índice FAISS + búsqueda semántica).

Vive aparte del pipeline live de Hermes: usa su propia base DuckDB
(`data/medallion.duckdb`) y no importa nada de `src/brain/` ni `src/execution/`.
"""
