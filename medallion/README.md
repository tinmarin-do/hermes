# Medallón light — noticias cripto (entregable diplomado)

Arquitectura medallón **Bronze → Silver → Gold** sobre el dominio del proyecto
[Hermes](../README.md): noticias de mercado cripto. Es una **rama aparte y
autocontenida** (`diplomado/medallion`): no importa nada de `src/`, escribe en su
propia base DuckDB y no toca el pipeline de trading.

- **Fuente**: feeds RSS públicos de CoinDesk, Cointelegraph y Decrypt — **sin
  autenticación**, sin API key, sin cuenta.
- **Stack**: Python 3.12 · DuckDB · Pydantic v2 · sentence-transformers
  (`all-MiniLM-L6-v2`, 384-d, CPU) · FAISS · Docker Compose.

📄 **Informe para entregar:
[`informe/de-bronce-a-oro.pdf`](informe/de-bronce-a-oro.pdf)** (8 páginas,
LaTeX en [`informe/de-bronce-a-oro.tex`](informe/de-bronce-a-oro.tex) — el nombre,
la materia y el link al repo se editan en las primeras líneas del `.tex`;
recompilar con `latexmk -xelatex de-bronce-a-oro.tex`).

---

## Cómo correr

### Con Docker (recomendado)

```bash
cd medallion
docker compose build

docker compose run --rm medallion                                  # corrida 1 — lote nuevo
docker compose run --rm medallion                                  # corrida 2 — segundo lote
docker compose run --rm medallion python -m medallion run --batch-id <ID>   # reproceso del MISMO lote
docker compose run --rm medallion python -m medallion search "texto libre"
```

### Local (sin contenedor)

```bash
pip install -r medallion/requirements.txt
python -m medallion run          # desde la raíz del repo
pytest medallion/tests -o addopts=""
```

Los datos viven en `../data/` (montado como volumen): bronze crudo, DuckDB e
índice FAISS **sobreviven al contenedor**, que es lo que permite demostrar
idempotencia entre corridas.

---

## Criterio → dónde está implementado

| Criterio | Implementación | Evidencia |
|---|---|---|
| **Bronze**: 2+ lotes crudos, timestamp, sin transformar | [`bronze.py`](bronze.py) — payload guardado byte a byte en `data/medallion/bronze/<batch_id>/<source>.xml` **y** en `bronze_batches` con SHA-256. `batch_id` = timestamp UTC de la corrida. Cero parseo, cero limpieza en esta capa. | Tabla 1 de [`EVIDENCIA.md`](EVIDENCIA.md) |
| **Contrato**: validación explícita, cuarentena con motivo | [`contracts.py`](contracts.py) — `NewsItem` (Pydantic v2, `extra="forbid"`): largos mínimos, URL http(s), fecha plausible, símbolos en whitelist, `news_id` consistente. Lo que falla va a `silver_rejects` con **campo + tipo de error + mensaje + registro crudo**. | Tabla 2 |
| **Idempotencia**: reproceso ⇒ `filas_nuevas = 0` | [`silver.py`](silver.py) — staging `stg_news` (recreada por corrida, deduplicada con `QUALIFY row_number()`) → `INSERT … ON CONFLICT (news_id) DO UPDATE` (UPSERT/MERGE). Cada corrida deja su renglón en `load_audit`. | Tabla 3 |
| **Duplicados**: `COUNT(*) > 1` por clave natural = 0 filas | Clave natural `news_id = sha256(source \| url)[:32]`, declarada **PRIMARY KEY** de `silver_news`. | Tabla 4 |
| **Gold**: índice vectorial funcional + consulta semántica | [`gold.py`](gold.py) — embeddings MiniLM sobre `título. cuerpo` → `faiss.IndexFlatIP` con vectores L2-normalizados (producto interno = coseno), persistido en `data/medallion/gold/news.faiss`. `search(query, k)` expone la búsqueda. | Tabla 5 |

---

## Decisiones de diseño

**Clave natural = `sha256(source | url)`.** No el título (cambia con las
ediciones del editor) ni el GUID del feed (cada fuente lo formatea distinto). La
URL es lo que identifica la nota en el dominio real.

**El UPSERT distingue "vi esto otra vez" de "esto cambió".** `content_hash`
resume título+cuerpo+fecha+símbolos; `updated_at` sólo se mueve cuando el hash
cambia. Así `filas_nuevas = 0` y `filas_actualizadas = 0` en un reproceso puro,
y una corrección editorial sí queda registrada.

**Bronze es inmutable.** `ON CONFLICT DO NOTHING`: un lote ya escrito jamás se
sobrescribe. La limpieza de HTML ocurre en Silver, no antes — si se limpiara en
Bronze ya no sería crudo y se perdería la posibilidad de re-parsear con reglas
nuevas.

**`IndexFlatIP` y no un índice aproximado (IVF/HNSW).** Con ~100–500 notas la
búsqueda exhaustiva es exacta e instantánea; un índice aproximado sólo agregaría
hiperparámetros que calibrar sin ganancia medible a esta escala.

**La cuarentena también es idempotente** (PK `batch_id + source + record_ord`):
reprocesar un lote no infla la tabla de rechazos.

## Limitaciones honestas

- El modelo `all-MiniLM-L6-v2` es **monolingüe (inglés)**, igual que el corpus.
  Una consulta en español recupera resultados mucho más pobres; para producción
  bilingüe habría que cambiar a `paraphrase-multilingual-MiniLM-L12-v2`.
- Los feeds RSS entregan sólo el resumen (`description`), no la nota completa:
  los embeddings describen el *abstract*, no el cuerpo entero.
- La inferencia de símbolos es por palabras clave, no NER — suficiente para
  etiquetar, insuficiente para desambiguar (`LINK` como palabra común, p. ej.).
