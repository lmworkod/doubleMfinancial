import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

from app import monitor


def test_intraday_drop_alert_and_deduplication(monkeypatch):
    observed = datetime.now(UTC)
    holding = SimpleNamespace(symbol="NVDA", quantity=2.0, average_cost=100.0)
    quote = {"price": 94.0, "open": 100.0, "as_of": observed, "source": "yahoo_intraday_5m"}
    values = {}
    monkeypatch.setattr(monitor.db, "get_holdings", lambda: [holding])
    monkeypatch.setattr(monitor.db, "get_watchlist_symbols", lambda: ["NVDA", "SPY"])
    async def intraday(symbol):
        return quote if symbol == "NVDA" else None
    monkeypatch.setattr(monitor.market_data, "intraday_quote", intraday)
    monkeypatch.setattr(monitor.db, "get_metric", lambda key: values.get(key))
    monkeypatch.setattr(monitor.db, "set_metric", lambda key, value: values.__setitem__(key, SimpleNamespace(value=value)))
    class Services:
        async def daily_history(self, symbol, outputsize=64):
            return ([(observed, 100.0)] * 64, None)
    alerts = asyncio.run(monitor.scan_intraday_drops(Services()))
    assert len(alerts) == 1
    assert "<b>NVDA (NVDA)</b>" in alerts[0]
    assert "-6.00%" in alerts[0]
    assert "2 unidades" in alerts[0]
    assert values["intraday_drop_alert_NVDA"].value == observed.date().isoformat()
    assert asyncio.run(monitor.scan_intraday_drops(Services())) == []


def test_intraday_drop_does_not_alert_at_four_percent(monkeypatch):
    observed = datetime.now(UTC)
    quote = {"price": 96.0, "open": 100.0, "as_of": observed, "source": "yahoo_intraday_5m"}
    monkeypatch.setattr(monitor.db, "get_holdings", list)
    monkeypatch.setattr(monitor.db, "get_watchlist_symbols", lambda: ["SPY"])
    async def intraday(symbol):
        return quote
    monkeypatch.setattr(monitor.market_data, "intraday_quote", intraday)
    monkeypatch.setattr(monitor.db, "get_metric", lambda key: None)
    monkeypatch.setattr(monitor.db, "set_metric", lambda key, value: None)
    assert asyncio.run(monitor.scan_intraday_drops(object())) == []
