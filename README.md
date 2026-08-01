# Arquitectura medallón sobre noticias de mercado cripto

**Práctica Módulo 1 — Diplomado de AI · Augmented Humans**
Erika Jimenez · 31 de julio de 2026

Pipeline **Bronze → Silver → Gold** sobre un corpus de noticias de criptoactivos:
ingesta cruda verificable, contrato de datos con cuarentena, carga idempotente y
búsqueda semántica vectorial. Todo corre en contenedor y se reproduce desde cero
con tres comandos.

- **Fuente**: feeds RSS públicos de CoinDesk, Cointelegraph y Decrypt — **sin
  autenticación**, sin API key, sin cuenta.
- **Stack**: Python 3.12 · DuckDB · Pydantic v2 · sentence-transformers
  (`all-MiniLM-L6-v2`, 384-d, CPU) · FAISS · Docker Compose.
- **Tamaño**: 1 176 líneas de Python, 15 pruebas automatizadas offline.

📄 **Informe del entregable: [`informe/de-bronce-a-oro.pdf`](informe/de-bronce-a-oro.pdf)**
(8 páginas). Fuente LaTeX en [`informe/de-bronce-a-oro.tex`](informe/de-bronce-a-oro.tex);
los datos de portada se editan en sus primeras líneas y se recompila con
`latexmk -xelatex de-bronce-a-oro.tex`.

📊 **Evidencia de ejecución: [`EVIDENCIA.md`](EVIDENCIA.md)** — salida literal de
las cuatro corridas end-to-end.

---

## Sobre esta rama

Esto es una **adaptación para el diplomado de la rama `main`** de este mismo repo.
`main` contiene **Hermes**, un proyecto propio de investigación cuantitativa sobre
mercados cripto —experimental y educativo, no asesoría financiera—; esta rama
(`diplomado/medallion`) sale de ahí y se depuró hasta dejar **únicamente la
práctica**: los archivos de Hermes se eliminaron *de esta rama*, no de `main`.

De la base original se conservó el **dominio**: noticias de mercado cripto y las
mismas fuentes RSS. El pipeline medallón, en cambio, se escribió **desde cero**
para la práctica, porque el de Hermes no cumple los criterios pedidos:

- limpia el HTML **antes** de guardar, así que su capa cruda no es cruda;
- no tiene contrato declarativo (`BaseModel`) ni tabla de cuarentena;
- sus embeddings alimentan un *clustering*, sin índice vectorial ni búsqueda.

Consecuencia práctica: este código no importa nada de `main` y se corre solo.
Para ver el proyecto del que desciende, cambiar a la rama `main`.

---

## Estructura

```
.
├── README.md                  este archivo
├── EVIDENCIA.md               salida literal de las 4 corridas E2E
├── informe/                   informe LaTeX + PDF del entregable
│   ├── de-bronce-a-oro.tex
│   ├── de-bronce-a-oro.pdf
│   └── salida-e2e.txt         anexo: salida sin editar de `medallion evidence`
├── medallion/                 el paquete Python
│   ├── bronze.py              ingesta cruda + SHA-256
│   ├── contracts.py           NewsItem (Pydantic v2), clave natural, símbolos
│   ├── silver.py              staging → UPSERT idempotente + cuarentena
│   ├── gold.py                embeddings + índice FAISS + search()
│   ├── db.py                  conexión DuckDB y esquema
│   ├── pipeline.py            CLI (run · ingest · silver · gold · search · evidence)
│   ├── tests/                 15 pruebas offline
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── requirements.txt       dependencias del pipeline
│   └── requirements-dev.txt   + pytest
└── data/                      generado, NO versionado (bronze crudo, DuckDB, FAISS)
```

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
docker compose run --rm medallion python -m medallion evidence     # tablas de evidencia (sólo lectura)
```

### Local (sin contenedor)

Desde la raíz del repo:

```bash
pip install -r medallion/requirements.txt      # sólo el pipeline
python -m medallion run

pip install -r medallion/requirements-dev.txt  # + pytest, para las pruebas
pytest medallion/tests
```

Las pruebas corren en el anfitrión, no dentro del contenedor: la imagen sólo
copia el paquete, no `tests/`.

Los datos viven en `data/`, montado como volumen desde `medallion/docker-compose.yml`:
bronze crudo, DuckDB e índice FAISS **sobreviven al contenedor**, que es
precisamente lo que permite demostrar idempotencia entre corridas separadas.

---

## Criterio → dónde está implementado

| Criterio | Implementación | Evidencia |
|---|---|---|
| **Bronze**: 2+ lotes crudos, timestamp, sin transformar | [`medallion/bronze.py`](medallion/bronze.py) — payload guardado byte a byte en `data/medallion/bronze/<batch_id>/<source>.xml` **y** en `bronze_batches` con SHA-256. `batch_id` = timestamp UTC de la corrida. Cero parseo, cero limpieza en esta capa. | Tabla 1 de [`EVIDENCIA.md`](EVIDENCIA.md) |
| **Contrato**: validación explícita, cuarentena con motivo | [`medallion/contracts.py`](medallion/contracts.py) — `NewsItem` (Pydantic v2, `extra="forbid"`): largos mínimos, URL http(s), fecha plausible, símbolos en whitelist, `news_id` consistente. Lo que falla va a `silver_rejects` con **campo + tipo de error + mensaje + registro crudo**. | Tabla 2 |
| **Idempotencia**: reproceso ⇒ `filas_nuevas = 0` | [`medallion/silver.py`](medallion/silver.py) — staging `stg_news` (recreada por corrida, deduplicada con `QUALIFY row_number()`) → `INSERT … ON CONFLICT (news_id) DO UPDATE` (UPSERT/MERGE). Cada corrida deja su renglón en `load_audit`. | Tabla 3 |
| **Duplicados**: `COUNT(*) > 1` por clave natural = 0 filas | Clave natural `news_id = sha256(source \| url)[:32]`, declarada **PRIMARY KEY** de `silver_news`. | Tabla 4 |
| **Gold**: índice vectorial funcional + consulta semántica | [`medallion/gold.py`](medallion/gold.py) — embeddings MiniLM sobre `título. cuerpo` → `faiss.IndexFlatIP` con vectores L2-normalizados (producto interno = coseno), persistido en `data/medallion/gold/news.faiss`. `search(query, k)` expone la búsqueda. | Tabla 5 |

---

## Las seis tablas

| Capa | Tabla | Rol |
|---|---|---|
| Bronze | `bronze_batches` | payload crudo por (lote, fuente) + SHA-256 |
| Silver | `stg_news` | *staging*, se recrea en cada corrida |
| Silver | `silver_news` | destino limpio, PK = clave natural |
| Silver | `silver_rejects` | cuarentena con campo, tipo y motivo |
| Gold | `gold_news_embeddings` | mapa `news_id` → posición en FAISS |
| — | `load_audit` | bitácora por corrida (evidencia de idempotencia) |

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

---

## Limitaciones honestas

- El modelo `all-MiniLM-L6-v2` es **monolingüe (inglés)**, igual que el corpus.
  Una consulta en español recupera resultados mucho más pobres; para producción
  bilingüe habría que cambiar a `paraphrase-multilingual-MiniLM-L12-v2`.
- Los feeds RSS entregan sólo el resumen (`description`), no la nota completa:
  los embeddings describen el *abstract*, no el cuerpo entero.
- La inferencia de símbolos es por palabras clave, no NER — suficiente para
  etiquetar, insuficiente para desambiguar (`LINK` como palabra común, p. ej.).

---

## Licencia

[PolyForm Noncommercial 1.0.0](LICENSE) — uso no comercial.
