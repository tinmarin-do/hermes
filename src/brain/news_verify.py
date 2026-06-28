"""News verification layer (PRD §8.7.2).

News is the LAST layer in the decision hierarchy: data → prediction → verification.
It can only CONFIRM or CONTRADICT a quant-derived thesis — never originate a trade.
Consumed ONLY by Risk and PM, never by Analysts or the bull/bear debate.

Golden rule (§8.7.1): only categorical features reach here — never raw news text.
"""
import os

# Cluster → directional lean. Conservative mapping; "macro"/"other" stay neutral.
BULLISH_CLUSTERS = {"protocol_upgrade", "listing"}
BEARISH_CLUSTERS = {"regulatory", "hack"}

CONFIRM_MAX = 1.2      # news confirming the thesis can boost confidence (capped)
CONTRADICT_MOD = 0.6   # news contradicting the thesis cuts confidence
LOW_TRUST_MOD = 0.7    # uncorroborated news is discounted further


def news_context(signal: dict | None) -> dict | None:
    """Extract categorical news features from a Gold signal. None if absent.

    Until the news pipeline lands, signals carry no news → returns None →
    downstream modifier is neutral (1.0). Forward-compatible by design.
    """
    if not signal:
        return None
    feats = signal.get("features", {})
    cluster = feats.get("news_cluster")
    if cluster is None:
        return None
    return {
        "news_cluster": cluster,
        "news_sentiment": feats.get("news_sentiment_score"),
        "trust_score": feats.get("trust_score"),
    }


def apply_news_modifier(confidence: float, signal: dict | None, action: str) -> tuple[float, str]:
    """Adjust quant confidence by news verification. Returns (new_confidence, note).

    News can only modulate (confirm/contradict), never flip direction.
    A HOLD is never turned into a trade here.
    """
    ctx = news_context(signal)
    if ctx is None or action not in {"BUY", "SELL"}:
        return confidence, "sin contexto de noticias (modificador neutral)"

    cluster = ctx["news_cluster"]
    trust = ctx.get("trust_score")
    trust_min = float(os.environ.get("NEWS_TRUST_MIN_SCORE", "0.5"))

    if cluster in BULLISH_CLUSTERS:
        news_dir = "BUY"
    elif cluster in BEARISH_CLUSTERS:
        news_dir = "SELL"
    else:
        return confidence, f"noticias neutrales (cluster={cluster})"

    if news_dir == action:
        modifier, verb = CONFIRM_MAX, "confirma"
    else:
        modifier, verb = CONTRADICT_MOD, "contradice"

    note_trust = ""
    if trust is not None and trust < trust_min:
        modifier *= LOW_TRUST_MOD
        note_trust = f", trust bajo ({trust:.2f}) → descuento extra"

    new_conf = round(min(confidence * modifier, 1.0), 3)
    note = f"noticias {verb} la tesis (cluster={cluster}){note_trust}: {confidence:.0%} → {new_conf:.0%}"
    return new_conf, note
