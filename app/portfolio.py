from dataclasses import dataclass

from app.db import get_holdings, quote_for


@dataclass
class PortfolioLine:
    symbol: str
    quantity: float
    price: float | None
    market_value: float | None
    average_cost: float | None
    pnl: float | None


def portfolio_snapshot() -> tuple[list[PortfolioLine], float, float]:
    lines, total, known = [], 0.0, 0
    for holding in get_holdings():
        quote = quote_for(holding.symbol)
        price = quote.price if quote else None
        value = price * holding.quantity if price is not None else None
        pnl = ((price - holding.average_cost) * holding.quantity
               if price is not None and holding.average_cost is not None else None)
        if value is not None:
            total += value
            known += 1
        lines.append(PortfolioLine(holding.symbol, holding.quantity, price, value,
                                   holding.average_cost, pnl))
    return lines, total, known / len(lines) if lines else 0.0
