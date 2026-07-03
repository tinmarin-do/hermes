"""Silver news clustering pipeline (PRD §8.7).

Bronze news → sentence-transformers embeddings → UMAP → **HDBSCAN (método FIJO,
decidido 2026-07-02 vía lab Fase 4.0)** → etiquetado semántico → silver_news_clusters.

El método NO se re-elige por corrida (rompería la comparabilidad de clusters entre
corridas — PRD §8.7): el arnés de evaluación (`_evaluate_clustering`) queda para
auditoría/re-calibración por drift. Config del lab: all-MiniLM-L6-v2 + UMAP 10d
cosine (n_neighbors=15, min_dist=0.0) + HDBSCAN(min_cluster_size=10, min_samples=5).
Etiquetado de clusters: heurístico determinista por default ($0); LLM opt-in.

Drift-aware: modelos persistidos y reutilizados; re-calibrar cuando la fracción de
ruido supere el umbral configurable.
"""

import os
import pickle
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.cluster import DBSCAN, AgglomerativeClustering, KMeans
from sklearn.metrics import (
    calinski_harabasz_score,
    davies_bouldin_score,
    silhouette_score,
)

from src.data.db import get_connection

EMBED_MODEL = os.environ.get("NEWS_EMBED_MODEL", "all-MiniLM-L6-v2")
# Config validada en el lab Fase 4.0 (391 titulares, 4 modelos × 18 configs) —
# ver EXPERIMENT_LOG. Overridable por env, pero el default ES la decisión.
CLUSTER_METHOD = os.environ.get("NEWS_CLUSTER_METHOD", "hdbscan")
HDBSCAN_MIN_CLUSTER_SIZE = int(os.environ.get("NEWS_HDBSCAN_MIN_CLUSTER_SIZE", "10"))
HDBSCAN_MIN_SAMPLES = int(os.environ.get("NEWS_HDBSCAN_MIN_SAMPLES", "5"))
UMAP_N_COMPONENTS = int(os.environ.get("NEWS_UMAP_N_COMPONENTS", "10"))
UMAP_N_NEIGHBORS = 15
UMAP_MIN_DIST = float(os.environ.get("NEWS_UMAP_MIN_DIST", "0.0"))
NOISE_FRAC_THRESHOLD = float(os.environ.get("NEWS_DRIFT_NOISE_THRESHOLD", "0.30"))
MODEL_DIR = Path(os.environ.get("HERMES_DUCKDB_PATH", "data/hermes.duckdb")).parent / "news_models"


def _hdbscan_params(n: int) -> tuple[int, int]:
    """min_cluster_size efectivo: el decidido (10), acotado para batches chicos.

    Con pocas noticias (n < 5×mcs) un mcs=10 colapsaría todo a ruido; se baja
    proporcionalmente con piso en 3 (el mínimo sano de HDBSCAN).
    """
    mcs = (
        max(3, min(HDBSCAN_MIN_CLUSTER_SIZE, n // 5))
        if n < HDBSCAN_MIN_CLUSTER_SIZE * 5
        else HDBSCAN_MIN_CLUSTER_SIZE
    )
    return mcs, min(HDBSCAN_MIN_SAMPLES, mcs)


SOURCE_WEIGHTS = {
    "whale_alert": 1.0,
    "cryptopanic": 0.7,
    "coindesk_rss": 0.6,
    "cointelegraph_rss": 0.6,
    "decrypt_rss": 0.6,
}

CLUSTER_METHODS = {
    "hdbscan": None,
    "kmeans": None,
    "agglomerative": None,
    "dbscan": None,
}

# bull / bear classification maps — used for deriving sentiment per cluster
CLUSTER_DIRECTION: dict[str, str] = {}


def _load_model() -> SentenceTransformer:
    return SentenceTransformer(EMBED_MODEL)


def _embed_texts(texts: list[str], model: SentenceTransformer) -> np.ndarray:
    return model.encode(texts, show_progress_bar=False, batch_size=32, normalize_embeddings=True)


def _ensure_model_dir() -> Path:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    return MODEL_DIR


def _load_or_fit_umap(embeddings: np.ndarray, force_recalibrate: bool = False) -> Any:
    import umap

    path = _ensure_model_dir() / "umap.pkl"
    if not force_recalibrate and path.exists():
        with open(path, "rb") as f:
            return pickle.load(f)

    reducer = umap.UMAP(
        n_components=UMAP_N_COMPONENTS,
        n_neighbors=min(UMAP_N_NEIGHBORS, len(embeddings) - 1),
        min_dist=UMAP_MIN_DIST,
        random_state=42,
        metric="cosine",
    )
    reducer.fit(embeddings)
    with open(path, "wb") as f:
        pickle.dump(reducer, f)
    return reducer


def _evaluate_clustering(reduced: np.ndarray, embeddings: np.ndarray) -> dict[str, dict[str, Any]]:
    """Arnés de AUDITORÍA: compara los 4 métodos con métricas no supervisadas.

    Ya NO elige el método de producción (fijado por el lab Fase 4.0 — HDBSCAN);
    se reporta en el summary para monitorear drift y re-validar la elección.
    """
    import hdbscan

    results: dict[str, dict[str, Any]] = {}
    n = len(reduced)
    if n < 4:
        return results

    # --- K-Means ---
    k = max(2, int(np.sqrt(n / 2)))
    km = KMeans(n_clusters=k, random_state=42, n_init=10)
    km_labels = km.fit_predict(reduced)
    results["kmeans"] = _score_method(reduced, km_labels, "kmeans")

    # --- HDBSCAN (params decididos) ---
    mcs, ms = _hdbscan_params(n)
    hdb = hdbscan.HDBSCAN(
        min_cluster_size=mcs, min_samples=ms, metric="euclidean", cluster_selection_method="eom"
    )
    hdb_labels = hdb.fit_predict(reduced)
    results["hdbscan"] = _score_method(reduced, hdb_labels, "hdbscan")
    try:
        results["hdbscan"]["dbcv"] = round(hdb.relative_validity_, 4)
    except Exception:
        results["hdbscan"]["dbcv"] = None

    # --- Agglomerative ---
    agg = AgglomerativeClustering(n_clusters=k, metric="euclidean", linkage="ward")
    agg_labels = agg.fit_predict(reduced)
    results["agglomerative"] = _score_method(reduced, agg_labels, "agglomerative")

    # --- DBSCAN ---
    db = DBSCAN(eps=0.5, min_samples=2, metric="euclidean")
    db_labels = db.fit_predict(reduced)
    results["dbscan"] = _score_method(reduced, db_labels, "dbscan")

    return results


def _score_method(scaled: np.ndarray, labels: np.ndarray, name: str) -> dict[str, Any]:
    unique = set(labels) - {-1}
    n_clusters = len(unique)
    n_noise = int((labels == -1).sum())

    result: dict[str, Any] = {
        "method": name,
        "n_clusters": n_clusters,
        "n_noise": n_noise,
        "silhouette": None,
        "davies_bouldin": None,
        "calinski_harabasz": None,
    }

    if n_clusters >= 2:
        valid = labels != -1
        try:
            result["silhouette"] = round(float(silhouette_score(scaled[valid], labels[valid])), 4)
        except Exception:
            pass
        try:
            result["davies_bouldin"] = round(
                float(davies_bouldin_score(scaled[valid], labels[valid])), 4
            )
        except Exception:
            pass
        try:
            result["calinski_harabasz"] = round(
                float(calinski_harabasz_score(scaled[valid], labels[valid])), 4
            )
        except Exception:
            pass

    return result


def _select_best_method(eval_results: dict[str, dict[str, Any]]) -> str:
    if not eval_results:
        return "hdbscan"

    def _rank(method: str, r: dict[str, Any]) -> float:
        score = 0.0
        if r.get("silhouette") is not None:
            score += r["silhouette"]
        if r.get("davies_bouldin") is not None:
            score -= r["davies_bouldin"] * 0.5
        if r.get("calinski_harabasz") is not None:
            score += r["calinski_harabasz"] / 1000
        if r.get("dbcv") is not None:
            score += r["dbcv"] * 0.5
        n_noise = r.get("n_noise", 0)
        n_total = max(n_noise + r.get("n_clusters", 1), 1)
        noise_ratio = n_noise / n_total
        if noise_ratio > 0.5:
            score -= noise_ratio * 2
        else:
            score -= noise_ratio
        return score

    ranked = sorted(eval_results.items(), key=lambda x: _rank(*x), reverse=True)
    return ranked[0][0]


def _compute_trust_scores(items: list[dict], embeddings: np.ndarray) -> list[float]:
    """Multi-source corroboration trust scoring (PRD §8.7.1).

    Trust = base_source_weight × corroboration_factor.
    Stories confirmed by N distinct sources get a boost.
    """
    n = len(items)
    if n == 0:
        return []

    sim_matrix = embeddings @ embeddings.T
    trust_scores: list[float] = []

    for i in range(n):
        base_weight = SOURCE_WEIGHTS.get(items[i]["source"], 0.5)
        neighbors = int((sim_matrix[i] >= 0.85).sum()) - 1
        corr_factor = 1.0 + 0.2 * min(neighbors, 4)
        trust_scores.append(round(min(base_weight * corr_factor, 1.0), 4))

    return trust_scores


def _label_clusters(
    items: list[dict], labels: np.ndarray, trust_scores: list[float]
) -> dict[int, str]:
    """Etiqueta semántica por cluster sobre la taxonomía fija de news_verify.

    Default: heurística determinista ($0 — la aceptación de Fase 4 exige costo LLM
    cero en el pipeline de datos). Opt-in con NEWS_LABEL_WITH_LLM=1: DeepSeek etiqueta
    con titulares representativos (costo ~centavos; la etiqueta sigue restringida a la
    taxonomía, y el texto va a un clasificador aislado, NUNCA a un LLM de decisión).
    """
    unique = sorted(set(labels) - {-1})
    if not unique:
        return {}

    use_llm = os.environ.get("NEWS_LABEL_WITH_LLM", "0") == "1"
    cluster_map: dict[int, str] = {}
    llm = None
    if use_llm:
        try:
            from src.brain.llm import get_llm

            llm = get_llm("analyst")
        except Exception:
            llm = None

    for cid in unique:
        mask = labels == cid
        indices = np.where(mask)[0]
        best = sorted(indices, key=lambda i: trust_scores[i], reverse=True)[:5]
        headlines = "\n".join(f"- {items[i]['title'][:200]}" for i in best)

        if llm is not None:
            try:
                from langchain_core.messages import HumanMessage, SystemMessage

                system = SystemMessage(
                    content=(
                        "You are a news classifier. Given a set of crypto news headlines "
                        "that share a common theme, respond with a single short label "
                        "(lowercase, snake_case). Pick from: regulatory, hack, "
                        "protocol_upgrade, listing, macro, partnership, adoption, "
                        "whale_movement, market_sentiment, or other. "
                        "Respond with ONLY the label, nothing else."
                    )
                )
                resp = llm.invoke([system, HumanMessage(content=headlines)])
                cluster_map[cid] = resp.content.strip().lower().replace(" ", "_")[:40]
                continue
            except Exception:
                pass

        cluster_map[cid] = _heuristic_label(headlines)

    return cluster_map


def _heuristic_label(headlines: str) -> str:
    lower = headlines.lower()
    if any(w in lower for w in ("hack", "exploit", "breach", "stolen", "drain")):
        return "hack"
    if any(w in lower for w in ("sec", "regulation", "lawsuit", "ban", "cftc", "doj")):
        return "regulatory"
    if any(w in lower for w in ("upgrade", "fork", "hard fork", "merge", "eip", "bip")):
        return "protocol_upgrade"
    if any(w in lower for w in ("listing", "listed", "exchange add", "now trading")):
        return "listing"
    if any(w in lower for w in ("partnership", "partner", "collaboration")):
        return "partnership"
    if any(w in lower for w in ("adopt", "accept", "integrate")):
        return "adoption"
    if any(w in lower for w in ("whale", "transfer", "wallet", "on-chain", "accumulat")):
        return "whale_movement"
    if any(w in lower for w in ("fed", "interest rate", "cpi", "inflation", "gdp", "macro")):
        return "macro"
    return "market_sentiment"


def _sentiment_from_cluster(cluster_label: str) -> float:
    from src.brain.news_verify import BEARISH_CLUSTERS, BULLISH_CLUSTERS

    if cluster_label in BULLISH_CLUSTERS:
        return 0.6
    if cluster_label in BEARISH_CLUSTERS:
        return -0.4
    return 0.0


def _cluster_fixed_method(reduced: np.ndarray, method: str) -> np.ndarray:
    """Corre el método de producción (fijo — decidido en el lab Fase 4.0).

    Directo sobre el espacio UMAP (mismo pipeline validado en el lab, sin scaler).
    """
    import hdbscan

    labels_path = _ensure_model_dir() / "news_cluster_labels.npy"
    labels: np.ndarray
    n = len(reduced)

    if method == "kmeans":
        k = max(2, int(np.sqrt(n / 2)))
        labels = KMeans(n_clusters=k, random_state=42, n_init=10).fit_predict(reduced)
    elif method == "agglomerative":
        k = max(2, int(np.sqrt(n / 2)))
        labels = AgglomerativeClustering(
            n_clusters=k, metric="euclidean", linkage="ward"
        ).fit_predict(reduced)
    elif method == "dbscan":
        labels = DBSCAN(eps=0.5, min_samples=2, metric="euclidean").fit_predict(reduced)
    else:  # hdbscan — el decidido (default)
        mcs, ms = _hdbscan_params(n)
        labels = hdbscan.HDBSCAN(
            min_cluster_size=mcs, min_samples=ms, metric="euclidean", cluster_selection_method="eom"
        ).fit_predict(reduced)

    np.save(str(labels_path), labels)
    return labels


def transform_news(force_recalibrate: bool = False) -> dict:
    """Run the full Silver news clustering pipeline.

    Returns summary dict with metrics, method, n_clusters, noise_frac, etc.
    """
    con = get_connection()
    rows = con.execute("""
        SELECT id, source, title, body, published_at, symbols, injection_flag
        FROM bronze_news
        WHERE injection_flag = FALSE AND title IS NOT NULL AND title != ''
        ORDER BY published_at DESC
    """).fetchall()

    if not rows:
        con.close()
        return {"n_news": 0, "message": "No clean news in Bronze"}

    cols = ["id", "source", "title", "body", "published_at", "symbols", "injection_flag"]
    items = [dict(zip(cols, r)) for r in rows]

    texts = [(it["title"] + " " + (it.get("body") or ""))[:1000] for it in items]

    model = _load_model()
    embeddings = _embed_texts(texts, model)

    umap_reducer = _load_or_fit_umap(embeddings, force_recalibrate)
    reduced = np.asarray(umap_reducer.transform(embeddings))

    # Método FIJO (lab Fase 4.0); el arnés corre solo como auditoría comparativa.
    method = CLUSTER_METHOD
    eval_results = _evaluate_clustering(reduced, embeddings)

    labels = _cluster_fixed_method(reduced, method)

    noise_frac = round(float((labels == -1).sum()) / max(len(labels), 1), 4)
    drift_alert = noise_frac > NOISE_FRAC_THRESHOLD

    trust_scores = _compute_trust_scores(items, embeddings)
    cluster_map = _label_clusters(items, labels, trust_scores)

    _persist_clusters(con, items, labels, cluster_map, trust_scores)

    con.close()

    return {
        "n_news": len(items),
        "n_clusters": len(cluster_map),
        "n_noise": int((labels == -1).sum()),
        "noise_frac": noise_frac,
        "drift_alert": drift_alert,
        "method": method,
        "cluster_labels": sorted(set(cluster_map.values())),
        "audit_metrics": eval_results,
    }


def _persist_clusters(
    con,
    items: list[dict],
    labels: np.ndarray,
    cluster_map: dict[int, str],
    trust_scores: list[float],
) -> int:
    now = datetime.now(UTC).replace(tzinfo=None)
    count = 0
    for it, label, trust in zip(items, labels, trust_scores):
        cid = int(label)
        is_noise = cid == -1
        cluster_label = cluster_map.get(cid) if not is_noise else None

        con.execute(
            """
            INSERT OR REPLACE INTO silver_news_clusters
                (id, source, published_at, cluster_id, cluster_label, is_noise, trust_score, computed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
            [
                it["id"],
                it["source"],
                it["published_at"],
                cid,
                cluster_label,
                is_noise,
                trust if not is_noise else 0.0,
                now,
            ],
        )
        count += 1
    return count
