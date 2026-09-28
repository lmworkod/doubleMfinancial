from dataclasses import dataclass

from app.config import settings
from app.db import get_holdings, quote_for
from app.fx import quote_currency, to_eur, usd_per_eur


@dataclass
class PortfolioLine:
    symbol: str
    quantity: float
    price: float | None
    currency: str
    market_value: float | None
    average_cost: float | None
    pnl: float | None


def portfolio_snapshot() -> tuple[list[PortfolioLine], float, float]:
    lines, total, known = [], 0.0, 0
    rate = usd_per_eur()
    for holding in get_holdings():
        quote = quote_for(holding.symbol)
        price = quote.price if quote else None
        currency = quote_currency(holding.symbol, settings.default_currency)
        raw_value = price * holding.quantity if price is not None else None
        value = to_eur(raw_value, currency, rate) if raw_value is not None else None
        raw_pnl = ((price - holding.average_cost) * holding.quantity
                   if price is not None and holding.average_cost is not None else None)
        pnl = to_eur(raw_pnl, currency, rate) if raw_pnl is not None else None
        if value is not None:
            total += value
            known += 1
        lines.append(PortfolioLine(holding.symbol, holding.quantity, price, currency, value,
                                   holding.average_cost, pnl))
    return lines, total, known / len(lines) if lines else 0.0
