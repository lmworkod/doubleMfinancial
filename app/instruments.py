"""Instrument identifiers and provider-specific listed symbols.

The portfolio stores ISINs as stable identifiers. Ticker, exchange and quote
currency are kept separately because providers use different symbol formats.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Instrument:
    isin: str
    name: str
    twelve_data_symbol: str | None
    twelve_data_exchange: str | None
    finnhub_symbol: str | None
    quote_currency: str
    exchange: str


# Only provider symbols with a known listing are configured. Coverage/plan
# entitlements are still verified by the runtime response, never guessed.
INSTRUMENTS: dict[str, Instrument] = {
    "IE000J80JTL1": Instrument(
        "IE000J80JTL1", "First Trust Clean Smart Infrastructure UCITS ETF",
        "GRID", "XMIL", None, "EUR", "Borsa Italiana"
    ),
    "IE0003Z9E2Y3": Instrument(
        "IE0003Z9E2Y3", "Global X Copper Miners UCITS ETF",
        "COPX", "XLON", None, "USD", "London Stock Exchange"
    ),
    "IE000UL6CLP7": Instrument(
        "IE000UL6CLP7", "Global X Silver Miners UCITS ETF",
        "SILV", "XLON", None, "USD", "London Stock Exchange"
    ),
    "IE000YU9K6K2": Instrument(
        "IE000YU9K6K2", "VanEck Space Innovators UCITS ETF",
        "JEDI", "XLON", None, "USD", "London Stock Exchange"
    ),
    "IE000KHX9DX6": Instrument(
        "IE000KHX9DX6", "WisdomTree Strategic Metals and Rare Earths Miners UCITS ETF",
        "RARE", "XLON", None, "USD", "London Stock Exchange"
    ),
    "IE00B4ND3602": Instrument(
        "IE00B4ND3602", "iShares Physical Gold ETC",
        "PPFB", "XETR", None, "EUR", "Xetra"
    ),
    "IE000M7V94E1": Instrument(
        "IE000M7V94E1", "VanEck Uranium and Nuclear Technologies UCITS ETF",
        "NUKL", "XETR", None, "EUR", "Xetra"
    ),
}


def resolve_symbol(symbol: str, provider: str) -> str | None:
    """Resolve an ISIN to a provider ticker; pass regular tickers through."""
    if provider not in {"twelve_data", "finnhub"}:
        raise ValueError(f"Unknown market-data provider: {provider}")

    key = symbol.strip().upper()
    item = INSTRUMENTS.get(key)
    if item is None:
        # Don't accidentally send an unsupported ISIN to a ticker endpoint.
        if key.startswith("IE") and len(key) == 12:
            return None
        return key

    if provider == "twelve_data":
        return item.twelve_data_symbol
    return item.finnhub_symbol


def resolve_exchange(symbol: str, provider: str) -> str | None:
    """Return the provider exchange code for a known instrument."""
    if provider != "twelve_data":
        return None
    item = INSTRUMENTS.get(symbol.strip().upper())
    return item.twelve_data_exchange if item else None
