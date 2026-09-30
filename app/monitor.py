"""Intraday drawdown alerts for holdings and the configured watchlist."""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from html import escape

from app import db
from app.instruments import INSTRUMENTS, instrument_name
from app.providers import market_data

logger = logging.getLogger(__name__)
INTRADAY_DROP_THRESHOLD = 0.05


def _name(symbol: str) -> str:
    item = INSTRUMENTS.get(symbol.upper())
    return instrument_name(symbol)


def _alert(symbol: str, price: float, open_price: float, observed_at: datetime,
           source: str, history: list[tuple[datetime, float]]) -> str:
    change = price / open_price - 1
    holding = next((item for item in db.get_holdings() if item.symbol.upper() == symbol), None)
    lines = [
        "🟢 <b>OPORTUNIDAD DE COMPRA · CAÍDA INTRADÍA</b>",
        f"<b>{escape(_name(symbol))} ({escape(symbol)})</b>",
        f"📉 Variación desde apertura: <b>{change:+.2%}</b>",
        f"💵 Precio: {price:,.4f} · Apertura: {open_price:,.4f}",
    ]
    if holding:
        value = price * holding.quantity
        lines.extend([
            f"💼 Posición actual: {holding.quantity:g} unidades · valor indicativo {value:,.2f}",
            (f"Coste medio: {holding.average_cost:,.4f} · P/L latente: "
             f"{(price / holding.average_cost - 1):+.2%}" if holding.average_cost and holding.average_cost > 0
             else "Coste medio: no registrado"),
        ])
    else:
        lines.append("💼 Posición actual: sin posición registrada (watchlist)")
    if len(history) >= 22:
        closes = [row[1] for row in history]
        lines.append(f"📊 Momentum 21 sesiones: {price / closes[-22] - 1:+.2%}")
    else:
        lines.append("📊 Momentum 21 sesiones: histórico insuficiente")
    if len(history) >= 64:
        closes = [row[1] for row in history]
        lines.append(f"📈 Momentum 63 sesiones: {price / closes[-64] - 1:+.2%}")
    else:
        lines.append("📈 Momentum 63 sesiones: histórico insuficiente")
    lines.extend([
        f"🔎 Fuente: {escape(source)} · observado: {escape(observed_at.isoformat())}",
        "<i>Alerta informativa basada en una caída respecto a la apertura; no garantiza infravaloración ni recomienda ejecutar una operación.</i>",
    ])
    return "\n".join(lines)


async def scan_intraday_drops(services) -> list[str]:
    """Alert once per symbol and market session on a verified >5% intraday drop."""
    symbols = sorted(set(db.get_watchlist_symbols()) |
                     {item.symbol.upper() for item in db.get_holdings()})
    alerts = []
    now = datetime.now(UTC)
    for symbol in symbols:
        try:
            quote = await market_data.intraday_quote(symbol)
            if quote is None or quote.get("price") is None or quote.get("open") is None:
                continue
            price, open_price = quote["price"], quote["open"]
            observed = quote["as_of"]
            if price <= 0 or open_price <= 0 or price / open_price - 1 > -INTRADAY_DROP_THRESHOLD:
                continue
            if observed is None or (now - observed).total_seconds() > 20 * 60:
                continue
            session = observed.astimezone(UTC).date().isoformat()
            metric_key = f"intraday_drop_alert_{symbol}"
            previous = db.get_metric(metric_key)
            if previous is not None and previous.value == session:
                continue
            history, _ = await services.daily_history(symbol, outputsize=64)
            alerts.append(_alert(symbol, price, open_price, observed, quote["source"], history))
            db.set_metric(metric_key, session)
        except Exception:
            logger.exception("Could not scan intraday drop for %s", symbol)
    return alerts
