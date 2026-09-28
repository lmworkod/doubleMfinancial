
import asyncio

import httpx

from app.providers import DailyBudget, MarketData, _positive_price


def test_positive_price_rejects_invalid_values():
    assert _positive_price("12.5") == 12.5
    for value in (None, "", "nan", "inf", "-1", "0", "not-a-price"):
        assert _positive_price(value) is None


def test_daily_budget_has_explicit_limit():
    budget = DailyBudget(limit=1)
    assert budget.consume()
    assert not budget.consume()


def test_quote_uses_twelve_data_quote_endpoint_and_validates_price(monkeypatch):
    from app import providers

    monkeypatch.setattr(providers.settings, "twelve_data_api_key", "test-key")
    monkeypatch.setattr(providers.settings, "finnhub_api_key", "")
    service = MarketData()
    calls = []

    async def get(url, params):
        calls.append((url, params))
        return httpx.Response(200, json={"close": "24.1", "symbol": "SPY"})

    service.client.get = get
    async def run():
        try:
            return await service.quote("SPY")
        finally:
            await service.close()

    result = asyncio.run(run())

    assert result.value == 24.1
    assert result.source == "twelve_data"
    assert calls[0][0].endswith("/quote")
    assert calls[0][1]["symbol"] == "SPY"


def test_quote_does_not_try_finnhub_for_known_european_isin(monkeypatch):
    from app import providers

    monkeypatch.setattr(providers.settings, "twelve_data_api_key", "")
    monkeypatch.setattr(providers.settings, "finnhub_api_key", "test-key")
    service = MarketData()
    calls = []

    async def get(url, params):
        calls.append(url)
        return httpx.Response(403, request=httpx.Request("GET", url))

    service.client.get = get
    async def run():
        try:
            return await service.quote("IE000M7V94E1")
        finally:
            await service.close()

    result = asyncio.run(run())

    assert result.value is None
    assert calls == []


def test_quote_does_not_leak_request_url_on_http_error(monkeypatch):
    from app import providers

    monkeypatch.setattr(providers.settings, "twelve_data_api_key", "secret-value")
    monkeypatch.setattr(providers.settings, "finnhub_api_key", "")
    service = MarketData()
    request_url = "https://api.twelvedata.com/quote?symbol=SPY&apikey=secret-value"

    async def get(url, params):
        request = httpx.Request("GET", request_url)
        return httpx.Response(404, request=request)

    service.client.get = get
    async def run():
        try:
            return await service.quote("SPY")
        finally:
            await service.close()

    result = asyncio.run(run())

    assert result.value is None
    assert "404" not in (result.error or "")
    assert "secret-value" not in (result.error or "")
    assert "twelvedata.com" not in (result.error or "")
