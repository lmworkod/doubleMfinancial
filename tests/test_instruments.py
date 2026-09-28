import pytest

from app.instruments import INSTRUMENTS, resolve_exchange, resolve_symbol


@pytest.mark.parametrize(
    ("isin", "ticker", "exchange"),
    [
        ("IE000J80JTL1", "GRID", "XMIL"),
        ("IE0003Z9E2Y3", "COPX", "XLON"),
        ("IE000UL6CLP7", "SILV", "XLON"),
        ("IE000YU9K6K2", "JEDI", "XLON"),
        ("IE000KHX9DX6", "RARE", "XLON"),
        ("IE00B4ND3602", "PPFB", "XETR"),
        ("IE000M7V94E1", "NUKL", "XETR"),
    ],
)
def test_known_isin_resolves_provider_ticker_and_exchange(isin, ticker, exchange):
    assert resolve_symbol(isin, "twelve_data") == ticker
    assert resolve_exchange(isin, "twelve_data") == exchange
    assert resolve_symbol(isin, "finnhub") is None
    assert resolve_exchange(isin, "finnhub") is None


def test_unknown_isin_is_not_sent_to_market_provider():
    assert resolve_symbol("IE0000000000", "twelve_data") is None
    assert resolve_symbol("IE0000000000", "finnhub") is None
    assert resolve_exchange("IE0000000000", "twelve_data") is None


def test_regular_ticker_passes_through():
    assert resolve_symbol("BVN", "twelve_data") == "BVN"
    assert resolve_symbol("SPY", "finnhub") == "SPY"
    assert resolve_exchange("SPY", "twelve_data") is None


def test_unknown_provider_fails_loudly():
    with pytest.raises(ValueError):
        resolve_symbol("SPY", "unknown")


def test_instrument_map_uses_isin_keys():
    assert all(key == item.isin for key, item in INSTRUMENTS.items())
