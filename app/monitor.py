"""Conservative change monitor for holdings and broad-market proxies.

Alerts describe observed price moves only. They are not trading instructions.
"""
import logging
from html import escape

from app import db

logger = logging.getLogger(__name__)

MARKET_PROXIES = ("SPY", "QQQ", "TLT", "GLD")
HOLDING_MOVE_THRESHOLD = 0.05
MARKET_MOVE_THRESHOLD = 0.03


def _observe(symbol: str, threshold: float, label: str) -> str | None:
    quote = db.quote_for(symbol)
    if quote is None or quote.price is None or quote.price <= 0:
        return None
    key = f"monitor_price_{label}_{symbol}"
    previous = db.get_metric(key)
    db.set_metric(key, str(quote.price))
    if previous is None:
        return None
    try:
        old_price = float(previous.value)
    except (TypeError, ValueError):
        return None
    if old_price <= 0:
        return None
    change = quote.price / old_price - 1
    if abs(change) < threshold:
        return None
    direction = "subida" if change > 0 else "caída"
    return (
        f"📣 <b>CAMBIO RELEVANTE DE {label.upper()}</b>\n"
        f"<b>{escape(symbol)}</b> · {direction} del {change:+.2%} "
        f"desde la última observación del monitor.\n"
        f"Precio observado: {quote.price:,.4f} · {escape(quote.observed_at.isoformat())}.\n"
        "Alerta descriptiva; no constituye una señal de compra o venta."
    )


async def scan_portfolio_signal_changes(services=None) -> list[str]:
    """Detect significant observed price changes; never emit unvalidated trade calls."""
    alerts = []
    for holding in db.get_holdings():
        try:
            alert = _observe(holding.symbol.upper(), HOLDING_MOVE_THRESHOLD, "cartera")
            if alert:
                alerts.append(alert)
        except Exception:
            # Keep scanning other positions if one quote or database read fails.
            logger.exception("Could not monitor holding %s", holding.symbol)
    for symbol in MARKET_PROXIES:
        try:
            alert = _observe(symbol, MARKET_MOVE_THRESHOLD, "mercado")
            if alert:
                alerts.append(alert)
        except Exception:
            logger.exception("Could not monitor market proxy %s", symbol)
    return alerts
