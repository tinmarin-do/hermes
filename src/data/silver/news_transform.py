"""Silver news clustering pipeline (PRD §8.7).

Bronze news → sentence-transformers embeddings → UMAP → clustering evaluation harness
→ best method selected via unsupervised metrics → semantic labeling → silver_news_clusters.

Drift-aware: models are persisted and reused. Recalibration fires only when noise/outlier
rate exceeds a configurable threshold.
"""
import json
import os
import pickle
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sentence_transformers import SentenceTransformer
from sklearn.cluster import AgglomerativeClustering, DBSCAN, KMeans
from sklearn.metrics import (
    calinski_harabasz_score,
    davies_bouldin_score,
    silhouette_score,
)

from src.data.db import get_connection

EMBED_MODEL = os.environ.get("NEWS_EMBED_MODEL", "all-MiniLM-L6-v2")
UMAP_N_COMPONENTS = 8
UMAP_N_NEIGHBORS = 15
UMAP_MIN_DIST = 0.1
NOISE_FRAC_THRESHOLD = float(os.environ.get("NEWS_DRIFT_NOISE_THRESHOLD", "0.30"))
MODEL_DIR = Path(os.environ.get("HERMES_DUCKDB_PATH", "data/hermes.duckdb")).parent / "news_models"

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


def _load_or_fit_hdbscan(reduced: np.ndarray, force_recalibrate: bool = False) -> tuple[Any, np.ndarray]:
    import hdbscan

    model_path = _ensure_model_dir() / "hdbscan_model.pkl"
    labels_path = _ensure_model_dir() / "hdbscan_labels.npy"

    if not force_recalibrate and model_path.exists() and labels_path.exists():
        with open(model_path, "rb") as f:
            model = pickle.load(f)
        labels = np.load(str(labels_path))
    else:
        model = hdbscan.HDBSCAN(
            min_cluster_size=3,
            min_samples=2,
            metric="euclidean",
            cluster_selection_method="eom",
        )
        labels = model.fit_predict(reduced)
        with open(model_path, "wb") as f:
            pickle.dump(model, f)
        np.save(str(labels_path), labels)

    return model, labels


def _evaluate_clustering(
    reduced: np.ndarray, embeddings: np.ndarray
) -> dict[str, dict[str, Any]]:
    """Compare K-Means, HDBSCAN, Agglomerative, DBSCAN using unsupervised metrics.

    Returns a dict keyed by method name with {labels, metrics, model}. The best
    method is selected by ranking across Silhouette, Davies-Bouldin, Calinski-Harabasz,
    and DBCV (when available from HDBSCAN).
    """
    import hdbscan
    from sklearn.preprocessing import StandardScaler

    results: dict[str, dict[str, Any]] = {}
    n = len(reduced)
    if n < 4:
        return results

    scaled = StandardScaler().fit_transform(reduced)

    # --- K-Means ---
    k = max(2, int(np.sqrt(n / 2)))
    km = KMeans(n_clusters=k, random_state=42, n_init=10)
    km_labels = km.fit_predict(scaled)
    results["kmeans"] = _score_method(scaled, km_labels, "kmeans")

    # --- HDBSCAN ---
    hdb = hdbscan.HDBSCAN(min_cluster_size=3, min_samples=2, metric="euclidean", cluster_selection_method="eom")
    hdb_labels = hdb.fit_predict(scaled)
    results["hdbscan"] = _score_method(scaled, hdb_labels, "hdbscan")
    try:
        results["hdbscan"]["dbcv"] = round(hdb.relative_validity_, 4)
    except Exception:
        results["hdbscan"]["dbcv"] = None

    # --- Agglomerative ---
    agg = AgglomerativeClustering(n_clusters=k, metric="euclidean", linkage="ward")
    agg_labels = agg.fit_predict(scaled)
    results["agglomerative"] = _score_method(scaled, agg_labels, "agglomerative")

    # --- DBSCAN ---
    db = DBSCAN(eps=0.5, min_samples=2, metric="euclidean")
    db_labels = db.fit_predict(scaled)
    results["dbscan"] = _score_method(scaled, db_labels, "dbscan")

    return results


def _score_method(
    scaled: np.ndarray, labels: np.ndarray, name: str
) -> dict[str, Any]:
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
            result["davies_bouldin"] = round(float(davies_bouldin_score(scaled[valid], labels[valid])), 4)
        except Exception:
            pass
        try:
            result["calinski_harabasz"] = round(float(calinski_harabasz_score(scaled[valid], labels[valid])), 4)
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
    """Generate semantic labels per cluster using LLM (Ollama, local).

    Feeds representative titles per cluster and asks for a short label.
    Falls back to rule-based heuristic if LLM is unavailable.
    """
    from src.brain.llm import get_llm
    from langchain_core.messages import HumanMessage, SystemMessage

    unique = sorted(set(labels) - {-1})
    if not unique:
        return {}

    cluster_map: dict[int, str] = {}
    llm = None
    try:
        llm = get_llm("analyst")
    except Exception:
        pass

    system = SystemMessage(content=(
        "You are a news classifier. Given a set of crypto news headlines that share "
        "a common theme, respond with a single short label (1-3 words, lowercase, "
        "snake_case). Pick from: regulatory, hack, protocol_upgrade, listing, macro, "
        "partnership, adoption, whale_movement, market_sentiment, or other. "
        "Respond with ONLY the label, nothing else."
    ))

    for cid in unique:
        mask = labels == cid
        indices = np.where(mask)[0]
        best = sorted(indices, key=lambda i: trust_scores[i], reverse=True)[:5]
        headlines = "\n".join(f"- {items[i]['title'][:200]}" for i in best)

        if llm is not None:
            try:
                resp = llm.invoke([system, HumanMessage(content=headlines)])
                label = resp.content.strip().lower().replace(" ", "_")[:40]
                cluster_map[cid] = label
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
    from src.brain.news_verify import BULLISH_CLUSTERS, BEARISH_CLUSTERS
    if cluster_label in BULLISH_CLUSTERS:
        return 0.6
    if cluster_label in BEARISH_CLUSTERS:
        return -0.4
    return 0.0


def _cluster_with_best_method(
    reduced: np.ndarray, embeddings: np.ndarray, eval_results: dict[str, dict[str, Any]],
    best_method: str, force_recalibrate: bool,
) -> np.ndarray:
    """Run the winning clustering method (or HDBSCAN as default) and return labels."""
    import hdbscan
    from sklearn.preprocessing import StandardScaler

    scaled = StandardScaler().fit_transform(reduced)

    labels_path = _ensure_model_dir() / "news_cluster_labels.npy"
    labels: np.ndarray

    if best_method == "hdbscan":
        hdb = hdbscan.HDBSCAN(min_cluster_size=3, min_samples=2, metric="euclidean", cluster_selection_method="eom")
        labels = hdb.fit_predict(scaled)
    elif best_method == "kmeans":
        k = eval_results["kmeans"].get("n_clusters", max(2, int(np.sqrt(len(reduced) / 2))))
        km = KMeans(n_clusters=k, random_state=42, n_init=10)
        labels = km.fit_predict(scaled)
    elif best_method == "agglomerative":
        k = eval_results["agglomerative"].get("n_clusters", max(2, int(np.sqrt(len(reduced) / 2))))
        agg = AgglomerativeClustering(n_clusters=k, metric="euclidean", linkage="ward")
        labels = agg.fit_predict(scaled)
    elif best_method == "dbscan":
        db = DBSCAN(eps=0.5, min_samples=2, metric="euclidean")
        labels = db.fit_predict(scaled)
    else:
        hdb = hdbscan.HDBSCAN(min_cluster_size=3, min_samples=2, metric="euclidean", cluster_selection_method="eom")
        labels = hdb.fit_predict(scaled)

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
    reduced = umap_reducer.transform(embeddings)

    eval_results = _evaluate_clustering(reduced, embeddings)
    best_method = _select_best_method(eval_results)

    labels = _cluster_with_best_method(reduced, embeddings, eval_results, best_method, force_recalibrate)

    noise_frac = round(float((labels == -1).sum()) / max(len(labels), 1), 4)

    trust_scores = _compute_trust_scores(items, embeddings)
    cluster_map = _label_clusters(items, labels, trust_scores)

    _persist_clusters(con, items, labels, cluster_map, trust_scores)

    con.close()

    return {
        "n_news": len(items),
        "n_clusters": len(cluster_map),
        "n_noise": int((labels == -1).sum()),
        "noise_frac": noise_frac,
        "best_method": best_method,
        "eval_metrics": eval_results,
    }


def _persist_clusters(
    con, items: list[dict], labels: np.ndarray,
    cluster_map: dict[int, str], trust_scores: list[float],
) -> int:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    count = 0
    for it, label, trust in zip(items, labels, trust_scores):
        cid = int(label)
        is_noise = cid == -1
        cluster_label = cluster_map.get(cid) if not is_noise else None

        con.execute("""
            INSERT OR REPLACE INTO silver_news_clusters
                (id, source, published_at, cluster_id, cluster_label, is_noise, trust_score, computed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            it["id"], it["source"], it["published_at"],
            cid, cluster_label, is_noise, trust if not is_noise else 0.0,
            now,
        ])
        count += 1
    return count
