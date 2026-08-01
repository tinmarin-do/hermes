"""Contrato de datos (Pydantic v2) de la capa Silver.

Todo registro que salga de Bronze debe validarse contra `NewsItem`. El que no
pasa NO entra a Silver: va a `silver_rejects` con campo, tipo y motivo del
rechazo (cuarentena trazable).
"""

import hashlib
import re
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SourceName = Literal["coindesk", "cointelegraph", "decrypt"]

# Whitelist Hermes (PRD §8.8): la nota se etiqueta con los símbolos que menciona.
WATCHLIST: dict[str, tuple[str, ...]] = {
    "BTC": ("btc", "bitcoin"),
    "ETH": ("eth", "ether", "ethereum"),
    "SOL": ("sol ", "solana"),
    "LINK": ("link", "chainlink"),
    "AVAX": ("avax", "avalanche"),
    "XRP": ("xrp", "ripple"),
}

MAX_FUTURE = timedelta(days=1)  # tolerancia de reloj del publisher
MAX_AGE = timedelta(days=365 * 3)


def natural_key(source: str, url: str) -> str:
    """Clave natural del dominio: la nota es única por (fuente, URL)."""
    return hashlib.sha256(f"{source}|{url.strip().lower()}".encode()).hexdigest()[:32]


def infer_symbols(text: str) -> list[str]:
    low = f" {text.lower()} "
    return [sym for sym, kws in WATCHLIST.items() if any(k in low for k in kws)]


class NewsItem(BaseModel):
    """Contrato explícito de una nota. Campos extra = rechazo (no silencio)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    news_id: Annotated[str, Field(min_length=32, max_length=32)]
    source: SourceName
    title: Annotated[str, Field(min_length=10, max_length=300)]
    url: Annotated[str, Field(min_length=12, max_length=2000)]
    body: Annotated[str, Field(min_length=40, max_length=8000)]
    published_at: datetime
    symbols: list[str] = Field(default_factory=list)

    @field_validator("url")
    @classmethod
    def _url_http(cls, v: str) -> str:
        if not re.match(r"^https?://[^\s]+\.[^\s]+", v):
            raise ValueError("la URL debe ser http(s) absoluta y con dominio")
        return v

    @field_validator("published_at")
    @classmethod
    def _fecha_plausible(cls, v: datetime) -> datetime:
        v = v.astimezone(UTC).replace(tzinfo=None) if v.tzinfo else v
        now = datetime.now(UTC).replace(tzinfo=None)
        if v > now + MAX_FUTURE:
            raise ValueError(f"published_at en el futuro ({v.isoformat()})")
        if v < now - MAX_AGE:
            raise ValueError(f"published_at más viejo que {MAX_AGE.days} días ({v.isoformat()})")
        return v

    @field_validator("symbols")
    @classmethod
    def _symbols_en_whitelist(cls, v: list[str]) -> list[str]:
        malos = [s for s in v if s not in WATCHLIST]
        if malos:
            raise ValueError(f"símbolos fuera de la whitelist: {malos}")
        return sorted(set(v))

    @model_validator(mode="after")
    def _id_consistente(self) -> "NewsItem":
        esperado = natural_key(self.source, self.url)
        if self.news_id != esperado:
            raise ValueError("news_id no corresponde a sha256(source|url)")
        return self

    def content_hash(self) -> str:
        """Huella del contenido — decide si un MERGE actualiza o deja igual."""
        partes = (self.title, self.body, self.published_at.isoformat(), ",".join(self.symbols))
        return hashlib.sha256("|".join(partes).encode()).hexdigest()[:32]
