"""Bronze news ingestion: multi-source fetch → injection scan → DuckDB.

Golden rule (PRD §8.7.1): raw text is stored here and scanned, but NEVER
flows to a decision LLM. Downstream layers consume categorical features only.
"""

import html
import json
import re
from datetime import UTC, datetime
from html.parser import HTMLParser

from src.data.bronze.injection_scanner import scan_batch
from src.data.bronze.news_sources import fetch_all
from src.data.db import get_connection

MAX_TEXT_LEN = 4000  # hard length cap on stored text


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _clean_html(text: str) -> str:
    """Strip HTML tags/entities — RSS bodies are full of markup that trips the
    injection scanner and pollutes embeddings. Returns plain collapsed text."""
    if not text:
        return ""
    parser = _TextExtractor()
    try:
        parser.feed(text)
        plain = "".join(parser.parts)
    except Exception:
        plain = re.sub(r"<[^>]+>", " ", text)
    plain = html.unescape(plain)
    return re.sub(r"\s+", " ", plain).strip()


def ingest_news(
    symbols: list[str],
    sources: list[str] | None = None,
    limit: int = 50,
    scan_injection: bool = True,
) -> dict:
    """Fetch from all sources, scan for injection, persist to bronze_news.

    Returns summary: {fetched, stored, flagged, by_source}.
    """
    items = fetch_all(symbols, sources, limit)
    if not items:
        return {"fetched": 0, "stored": 0, "flagged": 0, "by_source": {}}

    # clean HTML + length cap before anything touches the text
    for it in items:
        it["title"] = _clean_html(it.get("title") or "")[:MAX_TEXT_LEN]
        it["body"] = _clean_html(it.get("body") or "")[:MAX_TEXT_LEN]

    if scan_injection:
        items = scan_batch(items)
    else:
        for it in items:
            it["injection_flag"] = False
            it["injection_score"] = None

    con = get_connection()
    now = datetime.now(UTC).replace(tzinfo=None)
    stored = 0
    flagged = 0
    by_source: dict[str, int] = {}

    for it in items:
        con.execute(
            """
            INSERT OR REPLACE INTO bronze_news
                (id, source, url, title, body, published_at, symbols,
                 injection_flag, injection_score, ingested_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            [
                it["id"],
                it["source"],
                it.get("url"),
                it["title"],
                it.get("body"),
                it["published_at"],
                json.dumps(it.get("symbols", [])),
                it["injection_flag"],
                it.get("injection_score"),
                now,
            ],
        )
        stored += 1
        flagged += 1 if it["injection_flag"] else 0
        by_source[it["source"]] = by_source.get(it["source"], 0) + 1

    con.close()
    return {
        "fetched": len(items),
        "stored": stored,
        "flagged": flagged,
        "by_source": by_source,
    }
