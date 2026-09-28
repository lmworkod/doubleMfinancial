import pytest

from app.instruments import INSTRUMENTS, resolve_symbol


@pytest.mark.parametrize(
    ("isin", "ticker"),
    [
        ("IE000J80JTL1", "GRID"),
        ("IE0003Z9E2Y3", "COPX"),
        ("IE000UL6CLP7", "SILV"),
        ("IE000YU9K6K2", "JEDI"),
        ("IE000KHX9DX6", "RARE"),
        ("IE00B4ND3602", "PPFB:XETR"),
        ("IE000M7V94E1", "NUKL:XETR"),
    ],
)
def test_known_isin_resolves_to_provider_ticker(isin, ticker):
    assert resolve_symbol(isin, "twelve_data") == ticker
    assert resolve_symbol(isin, "finnhub") == ticker


def test_unknown_isin_is_not_sent_to_market_provider():
    assert resolve_symbol("IE00B4ND3602", "twelve_data") == "PPFB:XETR"
    assert resolve_symbol("IE000M7V94E1", "finnhub") == "NUKL.DE"


def test_regular_ticker_passes_through():
    assert resolve_symbol("BVN", "twelve_data") == "BVN"
    assert resolve_symbol("SPY", "finnhub") == "SPY"


def test_unknown_provider_fails_loudly():
    with pytest.raises(ValueError):
        resolve_symbol("SPY", "unknown")


def test_instrument_map_uses_isin_keys():
    assert all(key == item.isin for key, item in INSTRUMENTS.items())
