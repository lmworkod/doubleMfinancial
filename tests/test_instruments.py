import pytest

from app.instruments import INSTRUMENTS, resolve_symbol


@pytest.mark.parametrize(
    ("isin", "twelve_data", "finnhub"),
    [
        ("IE000J80JTL1", "GRID", None),
        ("IE0003Z9E2Y3", "COPX", None),
        ("IE000UL6CLP7", "SILV", None),
        ("IE000YU9K6K2", "JEDI", None),
        ("IE000KHX9DX6", "RARE", None),
        ("IE00B4ND3602", "PPFB:XETR", None),
        ("IE000M7V94E1", "NUKL:XETR", None),
    ],
)
def test_known_isin_resolves_only_verified_provider_symbols(isin, twelve_data, finnhub):
    assert resolve_symbol(isin, "twelve_data") == twelve_data
    assert resolve_symbol(isin, "finnhub") == finnhub


def test_unknown_isin_is_not_sent_to_market_provider():
    assert resolve_symbol("IE0000000000", "twelve_data") is None
    assert resolve_symbol("IE0000000000", "finnhub") is None


def test_regular_ticker_passes_through():
    assert resolve_symbol("BVN", "twelve_data") == "BVN"
    assert resolve_symbol("SPY", "finnhub") == "SPY"


def test_unknown_provider_fails_loudly():
    with pytest.raises(ValueError):
        resolve_symbol("SPY", "unknown")


def test_instrument_map_uses_isin_keys():
    assert all(key == item.isin for key, item in INSTRUMENTS.items())
