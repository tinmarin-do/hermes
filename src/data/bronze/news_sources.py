"""Multi-source news adapters. CryptoPanic is NOT the single source of truth (PRD §8.7.1).

Each source returns a list of normalized dicts:
  {id, source, url, title, body, published_at (datetime), symbols (list[str])}
"""
import os
import json
import hashlib
from datetime import datetime, timezone
from xml.etree import ElementTree

import httpx


def _stable_id(source: str, url: str, title: str) -> str:
    """Deterministic id so re-ingesting the same item dedupes cleanly."""
    raw = f"{source}|{url}|{title}".encode()
    return hashlib.sha1(raw).hexdigest()[:16]


def fetch_cryptopanic(symbols: list[str], limit: int = 50) -> list[dict]:
    """CryptoPanic free tier. Requires CRYPTOPANIC_API_KEY."""
    api_key = os.environ.get("CRYPTOPANIC_API_KEY", "")
    if not api_key:
        return []

    currencies = ",".join(s.split("/")[0] for s in symbols)
    url = "https://cryptopanic.com/api/v1/posts/"
    params = {"auth_token": api_key, "currencies": currencies, "public": "true"}

    items: list[dict] = []
    try:
        resp = httpx.get(url, params=params, timeout=20)
        resp.raise_for_status()
        for post in resp.json().get("results", [])[:limit]:
            title = post.get("title", "")
            link = post.get("url", "")
            items.append({
                "id": _stable_id("cryptopanic", link, title),
                "source": "cryptopanic",
                "url": link,
                "title": title,
                "body": post.get("body", "") or "",
                "published_at": _parse_iso(post.get("published_at")),
                "symbols": [c.get("code") for c in post.get("currencies", []) or []],
            })
    except (httpx.HTTPError, ValueError):
        return items
    return items


def _fetch_rss(source_name: str, url: str, symbols: list[str], limit: int = 50) -> list[dict]:
    """Generic RSS fetcher — free, no API key. Editorial sources for corroboration."""
    items: list[dict] = []
    try:
        resp = httpx.get(url, timeout=20, follow_redirects=True,
                         headers={"User-Agent": "Hermes/0.1 (news ingest)"})
        resp.raise_for_status()
        root = ElementTree.fromstring(resp.content)
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            desc = (item.findtext("description") or "").strip()
            pub = item.findtext("pubDate")
            items.append({
                "id": _stable_id(source_name, link, title),
                "source": source_name,
                "url": link,
                "title": title,
                "body": desc,
                "published_at": _parse_rfc822(pub),
                "symbols": _infer_symbols(title + " " + desc, symbols),
            })
            if len(items) >= limit:
                break
    except (httpx.HTTPError, ElementTree.ParseError):
        return items
    return items


def fetch_coindesk_rss(symbols: list[str], limit: int = 50) -> list[dict]:
    """CoinDesk — editorial house A."""
    return _fetch_rss("coindesk_rss", "https://www.coindesk.com/arc/outboundfeeds/rss/", symbols, limit)


def fetch_cointelegraph_rss(symbols: list[str], limit: int = 50) -> list[dict]:
    """CoinTelegraph — editorial house B (independent of CoinDesk)."""
    return _fetch_rss("cointelegraph_rss", "https://cointelegraph.com/rss", symbols, limit)


def fetch_decrypt_rss(symbols: list[str], limit: int = 50) -> list[dict]:
    """Decrypt — editorial house C."""
    return _fetch_rss("decrypt_rss", "https://decrypt.co/feed", symbols, limit)


def fetch_whale_alert(symbols: list[str], limit: int = 50) -> list[dict]:
    """Whale Alert — ON-CHAIN facts (PRD §8.7.1). The least manipulable source:
    verifiable transactions, not narrative. Requires WHALE_ALERT_API_KEY (free tier).
    Returns [] without a key — multi-source never aborts."""
    api_key = os.environ.get("WHALE_ALERT_API_KEY", "")
    if not api_key:
        return []

    bases = {s.split("/")[0].lower() for s in symbols}
    url = "https://api.whale-alert.io/v1/transactions"
    params = {"api_key": api_key, "min_value": 500000}

    items: list[dict] = []
    try:
        resp = httpx.get(url, params=params, timeout=20)
        resp.raise_for_status()
        for tx in resp.json().get("transactions", [])[:limit]:
            sym = (tx.get("symbol") or "").lower()
            if bases and sym not in bases:
                continue
            amount = tx.get("amount", 0)
            frm = tx.get("from", {}).get("owner_type", "unknown")
            to = tx.get("to", {}).get("owner_type", "unknown")
            title = f"On-chain: {amount:,.0f} {sym.upper()} {frm} → {to}"
            tx_hash = tx.get("hash", "")
            items.append({
                "id": _stable_id("whale_alert", tx_hash, title),
                "source": "whale_alert",
                "url": f"https://whale-alert.io/transaction/{sym}/{tx_hash}",
                "title": title,
                "body": json.dumps({k: tx.get(k) for k in ("blockchain", "amount_usd", "transaction_type")}),
                "published_at": _parse_epoch(tx.get("timestamp")),
                "symbols": [sym.upper()] if sym else [],
            })
    except (httpx.HTTPError, ValueError):
        return items
    return items


SOURCE_FETCHERS = {
    "cryptopanic": fetch_cryptopanic,        # aggregator + community voting
    "coindesk_rss": fetch_coindesk_rss,      # editorial A
    "cointelegraph_rss": fetch_cointelegraph_rss,  # editorial B
    "decrypt_rss": fetch_decrypt_rss,        # editorial C
    "whale_alert": fetch_whale_alert,        # on-chain facts (key-gated)
}


def fetch_all(symbols: list[str], sources: list[str] | None = None, limit: int = 50) -> list[dict]:
    if sources is None:
        raw = os.environ.get("NEWS_SOURCES",
                             "cryptopanic,coindesk_rss,cointelegraph_rss,decrypt_rss")
        sources = [s.strip() for s in raw.split(",")]

    all_items: list[dict] = []
    for src in sources:
        fetcher = SOURCE_FETCHERS.get(src)
        if fetcher:
            all_items.extend(fetcher(symbols, limit))
    return all_items


# ── helpers ──────────────────────────────────────────────────────────────────
def _parse_iso(s: str | None) -> datetime:
    if not s:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return datetime.now(timezone.utc).replace(tzinfo=None)


def _parse_rfc822(s: str | None) -> datetime:
    if not s:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    from email.utils import parsedate_to_datetime
    try:
        return parsedate_to_datetime(s).replace(tzinfo=None)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc).replace(tzinfo=None)


def _parse_epoch(ts: int | None) -> datetime:
    if not ts:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).replace(tzinfo=None)
    except (ValueError, OSError):
        return datetime.now(timezone.utc).replace(tzinfo=None)


def _infer_symbols(text: str, watchlist: list[str]) -> list[str]:
    """RSS has no structured symbols — infer from watchlist mentions."""
    text_low = text.lower()
    found = []
    for sym in watchlist:
        base = sym.split("/")[0].lower()
        names = {"btc": "bitcoin", "eth": "ethereum", "sol": "solana",
                 "bnb": "binance", "avax": "avalanche", "matic": "polygon"}
        if base in text_low or names.get(base, "###") in text_low:
            found.append(base.upper())
    return found
