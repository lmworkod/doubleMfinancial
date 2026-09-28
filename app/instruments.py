"""Instrument identifiers and provider symbols for the personal portfolio.

The database keeps the user's stable identifier (ISIN). Providers receive a
listed ticker instead. Listing currency is explicit; values are not silently
converted between currencies.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Instrument:
    isin: str
    name: str
    twelve_data_symbol: str | None
    finnhub_symbol: str | None
    quote_currency: str
    exchange: str


# Provider coverage is checked at runtime; a ticker does not guarantee
# availability or API entitlement.
INSTRUMENTS: dict[str, Instrument] = {
    "IE000J80JTL1": Instrument(
        "IE000J80JTL1", "First Trust Clean Smart Infrastructure UCITS ETF",
        "GRID", "GRID", "USD", "Borsa Italiana (GRID.MI not assumed)"
    ),
    "IE0003Z9E2Y3": Instrument(
        "IE0003Z9E2Y3", "Global X Copper Miners UCITS ETF",
        "COPX", "COPX", "USD", "London Stock Exchange"
    ),
    "IE000UL6CLP7": Instrument(
        "IE000UL6CLP7", "Global X Silver Miners UCITS ETF",
        "SILV", "SILV", "USD", "London Stock Exchange"
    ),
    "IE000YU9K6K2": Instrument(
        "IE000YU9K6K2", "VanEck Space Innovators UCITS ETF",
        "JEDI", "JEDI", "USD", "London Stock Exchange"
    ),
    "IE000KHX9DX6": Instrument(
        "IE000KHX9DX6", "WisdomTree Strategic Metals and Rare Earths Miners UCITS ETF",
        "RARE", "RARE", "USD", "London Stock Exchange"
    ),
    "IE00B4ND3602": Instrument(
        "IE00B4ND3602", "iShares Physical Gold ETC",
        "PPFB:XETR", "PPFB.DE", "EUR", "Xetra"
    ),
    "IE000M7V94E1": Instrument(
        "IE000M7V94E1", "VanEck Uranium and Nuclear Technologies UCITS ETF",
        "NUKL:XETR", "NUKL.DE", "EUR", "Xetra"
    ),
}

# These identifiers remain unmapped until the exact listing is verified.
UNMAPPED_ISINS = {"IE00B4ND3602", "IE000M7V94E1"}


def resolve_symbol(symbol: str, provider: str) -> str | None:
    """Resolve a known ISIN to a provider ticker.

    Unknown ISINs are not sent as exchange tickers. Regular ticker symbols
    pass through unchanged.
    """
    if provider not in {"twelve_data", "finnhub"}:
        raise ValueError(f"Unknown market-data provider: {provider}")

    key = symbol.strip().upper()
    item = INSTRUMENTS.get(key)
    if item is None:
        if key.startswith("IE") and len(key) == 12:
            return None
        return key

    if provider == "twelve_data":
        return item.twelve_data_symbol
    return item.finnhub_symbol
