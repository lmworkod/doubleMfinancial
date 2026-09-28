from app.fx import quote_currency, to_eur


def test_usd_to_eur_uses_usd_per_eur_rate():
    assert to_eur(114.03, "USD", 1.1403) == 100.0


def test_eur_amount_does_not_need_fx_rate():
    assert to_eur(100.0, "EUR", None) == 100.0


def test_missing_rate_does_not_fake_usd_conversion():
    assert to_eur(100.0, "USD", None) is None


def test_known_instruments_define_quote_currency():
    assert quote_currency("IE00B4ND3602") == "EUR"
    assert quote_currency("IE000M7V94E1") == "EUR"
    assert quote_currency("BVN") == "USD"
    assert quote_currency("XAU/EUR") == "EUR"
