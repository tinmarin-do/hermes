"""BitsoAdapter — ejecución LIVE long-only en Bitso (spot, CNBV) — F6.

Diseño (decisiones 2026-07-03, PRD §13):
- **Símbolo canónico = */USDT** (el de data/señales); `PAIR_MAP` traduce al par del
  venue. Dos bolsillos de quote: USDT (BTC/ETH/SOL/XRP) y USD (LINK/AVAX — no
  tienen /USDT en Bitso). Los pares /MXN se evitan: fees dobles (0.60/0.78%).
- **Long-only permanente** (spot no puede short — §8.8): un SELL solo puede reducir
  tenencia real; se capea al balance libre del base asset.
- **Maker-first** (fee 0.30% vs 0.36% taker): limit pasivo al mejor bid/ask propio,
  espera `maker_wait_s`, luego cancela y cae a market por el remanente.
- **Cap al balance**: un BUY nunca excede el quote libre de su bolsillo (se achica
  la orden y se reporta), un SELL nunca excede el base libre. Un desbalance entre
  bolsillos degrada, no rompe.
- Kill switch: cancela órdenes abiertas y frena; NO liquida tenencias (eso es
  decisión humana o /execution:kill explícito).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from time import sleep
from typing import Any

import ccxt

from src.execution.adapter import ExecutionAdapter
from src.execution.kill import kill_switch
from src.execution.models import OrderResult, Position
from src.execution.schema import ensure_execution_schema

# Canónico (data/señales, */USDT) → par real en Bitso.
PAIR_MAP = {
    "LINK/USDT": "LINK/USD",
    "AVAX/USDT": "AVAX/USD",
}

_BASE_ASSETS = ("BTC", "ETH", "SOL", "XRP", "LINK", "AVAX")


def _venue_pair(symbol: str) -> str:
    return PAIR_MAP.get(symbol, symbol)


def _quote_of(pair: str) -> str:
    return pair.split("/")[1]


class BitsoAdapter(ExecutionAdapter):
    def __init__(self, maker_wait_s: float = 45.0, exchange: Any = None) -> None:
        ensure_execution_schema()
        self.maker_wait_s = maker_wait_s
        self._poll_s = 5.0
        self._exchange = exchange if exchange is not None else self._build_exchange()

    @staticmethod
    def _build_exchange() -> Any:
        from src.secrets import get_secret

        api_key = get_secret("BITSO_API_KEY")
        secret = get_secret("BITSO_API_SECRET")
        return ccxt.bitso({"apiKey": api_key, "secret": secret, "enableRateLimit": True})

    # ── helpers ──────────────────────────────────────────────────────────────

    def _markets(self) -> dict[str, Any]:
        if not getattr(self._exchange, "markets", None):
            self._exchange.load_markets()
        return dict(self._exchange.markets)

    def _free(self, currency: str) -> float:
        bal = self._exchange.fetch_balance()
        return float((bal.get(currency) or {}).get("free", 0) or 0)

    def _amount_to_precision(self, pair: str, amount: float) -> float:
        try:
            return float(self._exchange.amount_to_precision(pair, amount))
        except Exception:
            return round(amount, 8)

    def _price_to_precision(self, pair: str, price: float) -> float:
        try:
            return float(self._exchange.price_to_precision(pair, price))
        except Exception:
            return round(price, 2)

    def _reject(self, run_id: str, symbol: str, action: str, reason: str) -> OrderResult:
        return OrderResult(
            order_id=str(uuid.uuid4()),
            run_id=run_id,
            symbol=symbol,
            action=action,
            quantity=0,
            status="REJECTED",
            error=reason[:200],
        )

    # ── ExecutionAdapter ─────────────────────────────────────────────────────

    def execute(self, decision: dict[str, Any], run_id: str) -> OrderResult:
        if not kill_switch.is_alive():
            return self._reject(
                run_id,
                decision.get("symbol", ""),
                decision.get("action", "HOLD"),
                "Kill switch active — trading halted",
            )

        action = decision.get("action", "HOLD")
        symbol = decision.get("symbol", "NONE")
        size_usd = float(decision.get("size_usd", 0))

        if action == "HOLD" or symbol == "NONE" or size_usd <= 0:
            return OrderResult(
                order_id=str(uuid.uuid4()),
                run_id=run_id,
                symbol=symbol,
                action=action,
                quantity=0,
                status="CANCELLED",
                error="HOLD or zero size — no order placed",
            )
        if action not in ("BUY", "SELL"):
            return self._reject(run_id, symbol, action, f"Acción no soportada: {action}")

        pair = _venue_pair(symbol)
        base, quote = pair.split("/")

        try:
            market = self._markets().get(pair)
            if market is None:
                return self._reject(run_id, symbol, action, f"Par {pair} no existe en Bitso")

            ticker = self._exchange.fetch_ticker(pair)
            bid = float(ticker.get("bid") or 0)
            ask = float(ticker.get("ask") or 0)
            last = float(ticker.get("last") or ticker.get("close") or 0)
            ref_price = (bid if action == "SELL" else ask) or last
            if ref_price <= 0:
                return self._reject(run_id, symbol, action, f"Sin precio para {pair}")

            amount = size_usd / ref_price

            # ── Cap al balance del bolsillo (long-only: SELL ≤ tenencia real) ──
            if action == "BUY":
                free_quote = self._free(quote)
                taker_fee = float(market.get("taker", 0.0036))
                # 0.995: headroom para no morir en el borde exacto del balance
                # (corrida 29cb1a50: rechazo por centavos/carrera del cancel)
                affordable = free_quote * 0.995 / (ref_price * (1 + taker_fee))
                if affordable < amount:
                    amount = affordable
            else:
                free_base = self._free(base)
                if free_base < amount:
                    amount = free_base

            amount = self._amount_to_precision(pair, amount)
            min_amount = float((market.get("limits", {}).get("amount", {}) or {}).get("min") or 0)
            min_cost = float((market.get("limits", {}).get("cost", {}) or {}).get("min") or 0)
            if amount <= 0 or amount < min_amount or amount * ref_price < min_cost:
                return self._reject(
                    run_id,
                    symbol,
                    action,
                    f"Orden bajo mínimo tras cap de balance: qty={amount} "
                    f"(min={min_amount}, min_cost=${min_cost})",
                )

            # ── Maker-first: limit pasivo en el propio lado del libro ──
            passive_price = self._price_to_precision(pair, bid if action == "BUY" else ask)
            order = self._exchange.create_order(
                pair, "limit", action.lower(), amount, passive_price
            )
            order_id = str(order.get("id", ""))

            filled, avg_price = self._wait_fill(pair, order_id)

            # ── Fallback taker por el remanente ──
            remainder = self._amount_to_precision(pair, amount - filled)
            if remainder > 0 and remainder >= min_amount:
                try:
                    self._exchange.cancel_order(order_id, pair)
                except Exception as exc:  # noqa: S110 — ya llena/cancelada; sigue el fallback
                    print(f"[bitso] cancel {order_id}: {exc} (continúa fallback)")
                # Esperar la LIBERACIÓN real de los fondos reservados por la limit.
                # El status "canceled" llega en ms pero el saldo tarda >10s en
                # descongelarse (0379 en 29cb1a50, c385db10 y 4da7d525 — esta última
                # CON el retry de status): la señal confiable es el balance libre.
                taker_fee = float(market.get("taker", 0.0036))
                if action == "BUY":
                    self._wait_funds_release(quote, remainder * ref_price * (1 + taker_fee))
                else:
                    self._wait_funds_release(base, remainder)
                mkt = self._create_market_with_retry(
                    pair, action.lower(), remainder, ref_price, taker_fee
                )
                mkt_filled = float(mkt.get("filled", 0) or 0)
                mkt_avg = float(mkt.get("average", 0) or 0)
                mkt_id = str(mkt.get("id", ""))
                if mkt_filled <= 0 and mkt_id:
                    # Bitso responde el create SIN fill (asíncrono) — consultar la orden
                    # real antes de declarar rechazo (bug cazado por live-validation-1:
                    # la orden llenó pero el response inmediato decía filled=0).
                    mkt_filled, mkt_avg = self._wait_fill(pair, mkt_id)
                mkt_avg = mkt_avg or ref_price
                if mkt_filled > 0:
                    total = filled + mkt_filled
                    avg_price = (
                        ((avg_price * filled) + (mkt_avg * mkt_filled)) / total
                        if total > 0
                        else ref_price
                    )
                    filled = total

            status = "FILLED" if filled > 0 else "REJECTED"
            filled_at = datetime.now(UTC).replace(tzinfo=None)
            fee_rate = (
                float(market.get("maker", 0.003))
                if remainder <= 0
                else float(market.get("taker", 0.0036))
            )
            cost = filled * (avg_price or ref_price)
            fee = round(cost * fee_rate, 6)

            self._persist_order(
                run_id, symbol, action, filled, avg_price or ref_price, status, filled_at, cost, fee
            )
            return OrderResult(
                order_id=order_id or str(uuid.uuid4()),
                run_id=run_id,
                symbol=symbol,
                action=action,
                quantity=filled,
                price=avg_price or ref_price,
                status=status,
                filled_at=filled_at,
                cost_usd=round(cost, 6),
                fee_usd=fee,
                error=None if status == "FILLED" else "Sin fill (limit cancelada, market falló)",
            )
        except ccxt.BaseError as exc:
            return self._reject(run_id, symbol, action, str(exc))

    def _wait_funds_release(self, currency: str, needed: float, timeout_s: float = 60.0) -> float:
        """Espera a que el saldo LIBRE de `currency` cubra `needed`. → último free visto.

        La latencia de liberación VARÍA (sonda 2026-07-04: 4.1s; corrida 4da7d525:
        >6s) y el status de la orden NO la refleja — vigilar el balance es la única
        señal confiable. Con timeout devuelve lo que haya: el caller dimensiona a eso.
        Cada espera se loguea: telemetría gratis de la distribución real de latencias
        (si un día los logs muestran ~40s, subir el techo ANTES de que muerda).
        """
        free = self._free(currency)
        step = self._poll_s
        waited = 0.0
        while free < needed and step > 0 and waited < timeout_s:
            sleep(step)
            waited += step
            free = self._free(currency)
        status = "liberada" if free >= needed else "TIMEOUT sin liberar"
        print(
            f"[bitso] reserva {currency} {status} tras {waited:.1f}s "
            f"(free=${free:.2f} / needed=${needed:.2f}, techo {timeout_s:.0f}s)"
        )
        return free

    def _create_market_with_retry(
        self, pair: str, side: str, amount: float, ref_price: float, taker_fee: float
    ) -> dict[str, Any]:
        """Market con UN reintento ante 0379: re-espera la liberación del saldo y
        dimensiona el retry a lo realmente disponible (no al monto teórico)."""
        try:
            return dict(self._exchange.create_order(pair, "market", side, amount))
        except ccxt.BaseError as exc:
            if "0379" not in str(exc) and "Insufficient" not in str(exc):
                raise
            print(f"[bitso] market {side} {amount} rebotó por reserva sin liberar — retry único")
            base, quote = pair.split("/")
            if side == "buy":
                free = self._wait_funds_release(quote, amount * ref_price * (1 + taker_fee))
                affordable = free * 0.995 / (ref_price * (1 + taker_fee))
            else:
                free = self._wait_funds_release(base, amount)
                affordable = free
            retry_amount = self._amount_to_precision(pair, min(amount, affordable))
            if retry_amount <= 0:
                raise
            return dict(self._exchange.create_order(pair, "market", side, retry_amount))

    def _wait_fill(self, pair: str, order_id: str) -> tuple[float, float]:
        """Espera el fill del limit maker hasta maker_wait_s. → (filled, avg_price)."""
        waited = 0.0
        filled = 0.0
        avg = 0.0
        while waited <= self.maker_wait_s:
            try:
                o = self._exchange.fetch_order(order_id, pair)
                filled = float(o.get("filled", 0) or 0)
                avg = float(o.get("average", 0) or 0)
                if o.get("status") == "closed":
                    return filled, avg
            except Exception as exc:
                print(f"[bitso] poll {order_id}: {exc} (reintenta)")
            if waited >= self.maker_wait_s:
                break
            sleep(self._poll_s)
            waited += self._poll_s
        return filled, avg

    @staticmethod
    def _persist_order(
        run_id: str,
        symbol: str,
        action: str,
        quantity: float,
        price: float,
        status: str,
        filled_at: datetime,
        cost_usd: float,
        fee_usd: float,
    ) -> None:
        from src.data.db import get_connection

        con = get_connection()
        try:
            con.execute(
                """
                INSERT OR REPLACE INTO execution_orders
                    (order_id, run_id, symbol, action, quantity, price, status,
                     filled_at, created_at, cost_usd, fee_usd)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    str(uuid.uuid4()),
                    run_id,
                    symbol,
                    action,
                    quantity,
                    price,
                    status,
                    filled_at,
                    filled_at,
                    cost_usd,
                    fee_usd,
                ],
            )
        finally:
            con.close()

    def get_positions(self) -> list[Position]:
        """Tenencias spot reales (fetch_balance) como posiciones long.

        entry_price y P&L salen del cost basis reconstruido de execution_orders
        (fix hallazgo G): el venue no guarda "mi costo", pero los fills sí. La
        parte de la tenencia SIN fills trackeados (depósitos/dust pre-Hermes) se
        marca al precio actual con P&L 0 — no se inventa historia.
        """
        positions: list[Position] = []
        try:
            bal = self._exchange.fetch_balance()
        except Exception:
            return positions
        try:
            from src.execution.costbasis import cost_basis

            basis = cost_basis()
        except Exception:
            basis = {}
        for asset in _BASE_ASSETS:
            qty = float((bal.get(asset) or {}).get("total", 0) or 0)
            if qty <= 0:
                continue
            canonical = f"{asset}/USDT"
            pair = _venue_pair(canonical)
            try:
                last = float(self._exchange.fetch_ticker(pair).get("last") or 0)
            except Exception:
                last = 0.0
            b = basis.get(canonical)
            entry, upnl, rpnl = last, 0.0, 0.0
            if b and b["qty"] > 1e-12 and qty > 0:
                tracked = min(qty, b["qty"])
                # entrada ponderada: parte trackeada a avg_cost, resto a precio actual
                entry = (b["avg_cost"] * tracked + last * (qty - tracked)) / qty
                upnl = round((last - b["avg_cost"]) * tracked, 6)
                rpnl = round(b["realized_pnl"], 6)
            positions.append(
                Position(
                    symbol=canonical,
                    action="BUY",
                    quantity=qty,
                    entry_price=entry,
                    current_price=last,
                    unrealized_pnl=upnl,
                    realized_pnl=rpnl,
                )
            )
        return positions

    def get_balance(self) -> float:
        """Caja libre total en USD-equivalente: bolsillo USDT + bolsillo USD (≈1:1)."""
        try:
            bal = self._exchange.fetch_balance()
            usdt = float((bal.get("USDT") or {}).get("free", 0) or 0)
            usd = float((bal.get("USD") or {}).get("free", 0) or 0)
            return usdt + usd
        except Exception:
            return 0.0

    def get_pockets(self) -> tuple[dict[str, float], dict[str, str]]:
        """(caja libre por bolsillo de quote, símbolo canónico → bolsillo).

        Alimenta el cap por bolsillo del allocator: los BUYs de cada quote no
        pueden exceder su caja (hallazgo 2026-07-03: equity $566 pero USDT $367
        no pagan un target de $430 en un par /USDT).
        """
        try:
            bal = self._exchange.fetch_balance()
        except Exception:
            return {}, {}
        pockets = {q: float((bal.get(q) or {}).get("free", 0) or 0) for q in ("USDT", "USD")}
        mapping = {f"{a}/USDT": _quote_of(_venue_pair(f"{a}/USDT")) for a in _BASE_ASSETS}
        return pockets, mapping

    def get_equity(self) -> float:
        """Equity total = caja (USDT+USD) + tenencias marcadas a precio actual.

        Es la fuente del budget dinámico (HERMES_BUDGET_SOURCE=wallet): el budget
        de cada corrida ES la cartera real de Bitso, deposite lo que deposite Erika.
        MXN residual queda fuera a propósito (no es moneda operable del sistema).
        """
        equity = self.get_balance()
        for p in self.get_positions():
            equity += p.quantity * (p.current_price or 0.0)
        return equity

    def kill(self) -> None:
        kill_switch.activate("BitsoAdapter kill called")
        for canonical in [f"{a}/USDT" for a in _BASE_ASSETS]:
            pair = _venue_pair(canonical)
            try:
                for o in self._exchange.fetch_open_orders(pair):
                    self._exchange.cancel_order(o["id"], pair)
            except Exception as exc:
                print(f"[bitso] kill/cancel {pair}: {exc}")
                continue

    def is_alive(self) -> bool:
        return kill_switch.is_alive()
