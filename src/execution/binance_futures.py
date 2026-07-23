"""Cliente Binance USDT-M Futures para el ejecutor H13 (F7).

Cliente REST firmado, deliberadamente chico y puro: el transporte HTTP es
inyectable (tests sin red), las keys llegan por argumento (el job las recibe de
Secret Manager como env — jamás se loguean), y la base URL cambia a testnet vía
`BINANCE_FUTURES_BASE`. NO implementa la interfaz del brain (pipeline live de
Bitso intocable): este cliente pertenece al ejecutor H13.

Reglas de la casa aplicadas aquí: la key NUNCA tiene permiso de retiro (#4);
margen AISLADO y apalancamiento 1x se fijan por símbolo antes de operar.
"""

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

MAINNET = "https://fapi.binance.com"
TESTNET = "https://testnet.binancefuture.com"

Transport = Callable[[str, str, dict[str, str]], tuple[int, Any]]


def _default_transport(method: str, url: str, headers: dict[str, str]) -> tuple[int, Any]:
    if not url.startswith("https://"):  # solo HTTPS a los hosts del venue (S310)
        raise ValueError(f"esquema no permitido: {url[:24]}")
    req = urllib.request.Request(url, headers=headers, method=method)  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {}


class BinanceFuturesClient:
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base: str = MAINNET,
        transport: Transport | None = None,
    ) -> None:
        self._key = api_key
        self._secret = api_secret.encode()
        self._base = base.rstrip("/")
        self._t: Transport = transport or _default_transport

    # ── plomería HTTP ───────────────────────────────────────────────────────
    def _public(self, path: str, params: dict[str, Any] | None = None) -> Any:
        qs = urllib.parse.urlencode(params or {})
        status, body = self._t("GET", f"{self._base}{path}?{qs}", {})
        if status != 200:
            raise RuntimeError(f"binance {path} HTTP {status}: {body}")
        return body

    def _signed(self, method: str, path: str, params: dict[str, Any] | None = None) -> Any:
        p = dict(params or {})
        p["timestamp"] = int(time.time() * 1000)
        p["recvWindow"] = 10_000
        qs = urllib.parse.urlencode(p)
        sig = hmac.new(self._secret, qs.encode(), hashlib.sha256).hexdigest()
        url = f"{self._base}{path}?{qs}&signature={sig}"
        status, body = self._t(method, url, {"X-MBX-APIKEY": self._key})
        if status != 200:
            code = body.get("code") if isinstance(body, dict) else None
            msg = body.get("msg", "") if isinstance(body, dict) else ""
            raise RuntimeError(f"binance {path} HTTP {status} code={code}: {msg[:160]}")
        return body

    # ── lecturas ────────────────────────────────────────────────────────────
    def exchange_filters(self) -> dict[str, dict[str, float]]:
        """Por símbolo PERPETUAL en TRADING: min_notional, step_size (LOT_SIZE)."""
        info = self._public("/fapi/v1/exchangeInfo")
        out: dict[str, dict[str, float]] = {}
        for s in info.get("symbols", []):
            if s.get("contractType") != "PERPETUAL" or s.get("status") != "TRADING":
                continue
            f = {x["filterType"]: x for x in s.get("filters", [])}
            out[s["symbol"]] = {
                "min_notional": float(f.get("MIN_NOTIONAL", {}).get("notional", 5.0)),
                "step_size": float(f.get("LOT_SIZE", {}).get("stepSize", 0.001)),
            }
        return out

    def mark_prices(self) -> dict[str, float]:
        return {r["symbol"]: float(r["markPrice"]) for r in self._public("/fapi/v1/premiumIndex")}

    def balance_usdt(self) -> float:
        for a in self._signed("GET", "/fapi/v2/balance"):
            if a.get("asset") == "USDT":
                return float(a["balance"])
        return 0.0

    def positions(self) -> dict[str, float]:
        """positionAmt firmado por símbolo (solo posiciones ≠ 0, modo one-way)."""
        out: dict[str, float] = {}
        for p in self._signed("GET", "/fapi/v2/positionRisk"):
            amt = float(p.get("positionAmt", 0.0))
            if amt != 0.0:
                out[p["symbol"]] = amt
        return out

    # ── setup por símbolo (idempotente; errores "ya estaba así" se toleran) ──
    def ensure_isolated_1x(self, symbol: str) -> None:
        try:
            self._signed(
                "POST", "/fapi/v1/marginType", {"symbol": symbol, "marginType": "ISOLATED"}
            )
        except RuntimeError as e:
            if "-4046" not in str(e):  # -4046 = "No need to change margin type"
                raise
        self._signed("POST", "/fapi/v1/leverage", {"symbol": symbol, "leverage": 1})

    # ── órdenes ──────────────────────────────────────────────────────────────
    def market_order(
        self, symbol: str, side: str, qty: float, reduce_only: bool = False
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": f"{qty:.10f}".rstrip("0").rstrip("."),
        }
        if reduce_only:
            params["reduceOnly"] = "true"
        result: dict[str, Any] = self._signed("POST", "/fapi/v1/order", params)
        return result


def round_step(qty: float, step: float) -> float:
    """Cantidad redondeada HACIA ABAJO al step del símbolo (jamás excede el target)."""
    if step <= 0:
        return qty
    return int(qty / step + 1e-9) * step
