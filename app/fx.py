"""Currency conversion helpers using ECB reference rates."""

from app import db


def quote_currency(symbol: str, fallback: str = "USD") -> str:
    """Return the trading currency for known ISINs and common FX symbols."""
    from app.instruments import INSTRUMENTS

    key = symbol.strip().upper()
    instrument = INSTRUMENTS.get(key)
    if instrument:
        return instrument.quote_currency
    if key.endswith("/EUR") or key.endswith("-EUR"):
        return "EUR"
    if key.endswith("/USD") or key.endswith("-USD"):
        return "USD"
    return fallback.upper()


def usd_per_eur() -> float | None:
    """Latest stored ECB rate, expressed as USD per EUR."""
    metric = db.get_metric("fx_usd_per_eur")
    if metric is None:
        return None
    try:
        rate = float(metric.value)
    except (TypeError, ValueError):
        return None
    return rate if rate > 0 else None


def to_eur(amount: float, currency: str, rate: float | None) -> float | None:
    """Convert an amount to EUR; return None when a required rate is missing."""
    currency = currency.upper()
    if currency == "EUR":
        return amount
    if currency == "USD" and rate is not None and rate > 0:
        return amount / rate
    return None
