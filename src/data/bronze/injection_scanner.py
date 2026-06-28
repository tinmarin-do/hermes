"""Prompt-injection scanner for incoming news (PRD §8.7.1).

Uses an off-the-shelf DeBERTa classifier (ProtectAI / Meta Prompt-Guard).
Lazy-loaded singleton so the model is read into memory only once.
"""

import os
from functools import lru_cache

INJECTION_THRESHOLD = 0.5


@lru_cache(maxsize=1)
def _get_classifier():
    """Lazy-load the HF text-classification pipeline. Cached across calls."""
    from transformers import pipeline

    # ProtectAI v1 is open + discriminates well in the crypto-news domain.
    # (deepset over-defends → flags ~80% of legit headlines; v2/Meta are gated.)
    model = os.environ.get(
        "NEWS_INJECTION_MODEL",
        "protectai/deberta-v3-base-prompt-injection",
    )
    return pipeline("text-classification", model=model, truncation=True, max_length=512)


def scan(text: str) -> tuple[bool, float]:
    """Return (is_injection, score). score is P(injection)."""
    if not text or not text.strip():
        return False, 0.0

    clf = _get_classifier()
    result = clf(text)[0]
    label = str(result.get("label", "")).upper()
    score = float(result.get("score", 0.0))

    # Models label injection as "INJECTION" or "1"; benign as "SAFE"/"LEGIT"/"0".
    is_injection = label in {"INJECTION", "1", "LABEL_1", "JAILBREAK"}
    p_injection = score if is_injection else 1.0 - score
    return (p_injection >= INJECTION_THRESHOLD), round(p_injection, 4)


def scan_batch(items: list[dict]) -> list[dict]:
    """Annotate each news dict with injection_flag and injection_score in-place."""
    for item in items:
        text = f"{item.get('title', '')} {item.get('body', '')}".strip()
        flag, score = scan(text)
        item["injection_flag"] = flag
        item["injection_score"] = score
    return items
