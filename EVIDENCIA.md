# Evidencia de ejecución — 2026-08-01

Todo lo de abajo es salida literal de `docker compose run --rm medallion …`
(imagen `medallion:light`, 459 MB). El pipeline corrió **cuatro veces** contra la
misma base montada en volumen: dos lotes distintos + un reproceso explícito de
cada uno.

| # | Comando | Lote | Resultado |
|---|---|---|---|
| 1 | `docker compose run --rm medallion` | `20260801T001833Z` (nuevo) | 91 filas nuevas |
| 2 | `docker compose run --rm medallion` | `20260801T001859Z` (nuevo) | **filas_nuevas = 0** |
| 3 | `… run --batch-id 20260801T001833Z` | reproceso lote 1 | **filas_nuevas = 0** |
| 4 | `… run --batch-id 20260801T001859Z` | reproceso lote 2 | **filas_nuevas = 0** |

---

## Cumplimiento de los criterios de aceptación

| Criterio | Mínimo pedido | Obtenido |
|---|---|---|
| Bronze | 2+ lotes crudos, timestamp, sin transformar | **2 lotes**, 116 368 bytes c/u, 3 payloads con SHA-256, guardados byte a byte |
| Contrato | validación explícita, cuarentena con motivo | 93 leídas → 91 válidas / **2 en cuarentena por lote**, motivo `body · string_too_short` |
| Idempotencia | reproceso da `filas_nuevas = 0` | **3 de 4 corridas con `filas_nuevas = 0`** (la primera, por definición, carga 91) |
| Duplicados | `COUNT(*) > 1` por clave natural = 0 filas | **0 filas**; 91 filas = 91 `news_id` distintos |
| Gold | índice vectorial funcional, 1+ consulta semántica | FAISS `IndexFlatIP` 384-d con 91 vectores, **3 consultas** demostradas |

---

## Salida literal

```text
==============================================================================
EVIDENCIA — arquitectura medallón  ·  2026-08-01 00:20:12Z  ·  db=/app/data/medallion.duckdb
==============================================================================

1) BRONZE — lotes crudos almacenados sin transformar
  batch_id          fuentes  fetched_at                  bytes_crudos  sha256_distintos
  ────────────────  ───────  ──────────────────────────  ────────────  ────────────────
  20260801T001833Z  3        2026-08-01 00:18:33.296624  116368        3
  20260801T001859Z  3        2026-08-01 00:18:59.808019  116368        3

2) CONTRATO Pydantic — válidos vs cuarentena por lote
  batch_id          leídas  válidas  rechazadas
  ────────────────  ──────  ───────  ──────────
  20260801T001833Z  93      91       2
  20260801T001859Z  93      91       2

   CUARENTENA — motivos de rechazo (silver_rejects)
  campo  tipo_error        motivo                                     n
  ─────  ────────────────  ─────────────────────────────────────────  ─
  body   string_too_short  String should have at least 40 characters  4

3) IDEMPOTENCIA — staging + MERGE por clave natural (news_id)
  run_id                batch_id          executed_at                 válidas  filas_nuevas  filas_actualizadas
  ────────────────────  ────────────────  ──────────────────────────  ───────  ────────────  ──────────────────
  run-20260801T001834Z  20260801T001833Z  2026-08-01 00:18:34.389178  91       91            0
  run-20260801T001900Z  20260801T001859Z  2026-08-01 00:19:00.572338  91       0             0
  run-20260801T001939Z  20260801T001833Z  2026-08-01 00:19:39.373690  91       0             0
  run-20260801T001953Z  20260801T001859Z  2026-08-01 00:19:53.335896  91       0             0

4) DUPLICADOS — news_id con COUNT(*) > 1 (debe ser 0 filas)
  (0 filas)
   filas en silver_news = 91  ·  news_id distintos = 91

5) GOLD — índice vectorial FAISS
  vectores  vec_ord_distintos  modelo                                  dim
  ────────  ─────────────────  ──────────────────────────────────────  ───
  91        91                 sentence-transformers/all-MiniLM-L6-v2  384

   BÚSQUEDA SEMÁNTICA — "lawsuit and regulatory crackdown by financial authorities"
  score   fuente         título                                                                símbolos
  ──────  ─────────────  ────────────────────────────────────────────────────────────────────  ────────
  0.4627  cointelegraph  New York sues Kalshi over alleged illegal gambling operation          ["ETH"]
  0.4091  coindesk       New York sues Kalshi, alleges it offers a gambling platform 'plain a  []
  0.3604  coindesk       The good and the bad of perps, according to crypto traders            []

   BÚSQUEDA SEMÁNTICA — "institutional money flowing into spot ETFs"
  score   fuente         título                                                                símbolos
  ──────  ─────────────  ────────────────────────────────────────────────────────────────────  ──────────────
  0.5666  cointelegraph  Bitcoin ETFs post $233M inflows, pushing week back into the green     ["BTC"]
  0.5391  decrypt        Bitcoin, Ethereum Wobble as Fed Holds Rates Steady                    ["BTC", "ETH"]
  0.4162  cointelegraph  Aviva Investors launches tokenized fund after Central Bank of Irelan  ["XRP"]

   BÚSQUEDA SEMÁNTICA — "sharp market selloff and price volatility"
  score   fuente    título                                                                símbolos
  ──────  ────────  ────────────────────────────────────────────────────────────────────  ──────────────
  0.4124  coindesk  Bitcoin’s calm is back and so is the setup for a volatility explosio  ["BTC"]
  0.3029  coindesk  Bitcoin, ether fall, equities rally with broader crypto market on tr  ["BTC", "ETH"]
  0.3014  coindesk  Bitcoin holds monthly gain, faces 'choppy' August as 'forced-selling  ["BTC"]

==============================================================================
  [PASA] bronze_2_lotes
  [PASA] cuarentena_con_motivo
  [PASA] reproceso_filas_nuevas_0
  [PASA] sin_duplicados
  [PASA] indice_vectorial
==============================================================================
```

---

## Por qué la búsqueda es semántica y no textual

La consulta **"lawsuit and regulatory crackdown by financial authorities"**
recupera *"New York **sues** Kalshi over alleged illegal gambling operation"*.
Ni "lawsuit", ni "regulatory", ni "crackdown", ni "authorities" aparecen en ese
titular: un `LIKE '%lawsuit%'` habría devuelto cero filas. Lo mismo con
"institutional money flowing into spot ETFs" → *"Bitcoin ETFs post $233M
**inflows**"*, y con "sharp market selloff" → *"the setup for a **volatility
explosion**"*.

## Tests

```console
$ pip install -r medallion/requirements-dev.txt
$ pytest medallion/tests
15 passed in 1.24s
```

Cubren, sin red y sin bajar el modelo (embeddings sustituidos por un hash
determinista): aceptación/rechazo del contrato campo por campo, cuarentena con
motivo, reproceso triple con `filas_nuevas = 0`, dos lotes idénticos sin generar
duplicados, cuarentena que no se infla al reprocesar, e índice FAISS incremental.

## Nota sobre `filas_nuevas = 0` en la corrida 2

La corrida 2 bajó un **lote nuevo** (`20260801T001859Z`, timestamp y SHA-256
propios) 26 segundos después del primero. Como los feeds no habían publicado
nada nuevo en ese lapso, las 91 notas ya existían y el MERGE las reconoció por
clave natural: `filas_nuevas = 0`. Es exactamente el comportamiento que se busca
—la deduplicación es por **contenido**, no por lote— y las corridas 3 y 4
demuestran el caso estricto que pide el criterio: reprocesar el *mismo* `batch_id`.
