from datetime import UTC, datetime
from types import SimpleNamespace

from app import monitor


def test_monitor_primes_baseline_without_alerts(monkeypatch):
    values = {}
    quote = SimpleNamespace(price=100.0, observed_at=datetime(2026, 9, 29, tzinfo=UTC))
    monkeypatch.setattr(monitor.db, "get_holdings", lambda: [])
    monkeypatch.setattr(monitor.db, "quote_for", lambda symbol: quote)
    monkeypatch.setattr(monitor.db, "get_metric", lambda key: values.get(key))
    monkeypatch.setattr(
        monitor.db, "set_metric",
        lambda key, value: values.__setitem__(key, SimpleNamespace(value=value)),
    )

    import asyncio
    assert asyncio.run(monitor.scan_portfolio_signal_changes()) == []
    assert values["monitor_price_mercado_SPY"].value == "100.0"


def test_monitor_alerts_only_above_market_threshold(monkeypatch):
    values = {"monitor_price_mercado_SPY": SimpleNamespace(value="100.0")}
    quote = SimpleNamespace(price=104.0, observed_at=datetime(2026, 9, 29, tzinfo=UTC))
    monkeypatch.setattr(monitor.db, "get_holdings", lambda: [])
    monkeypatch.setattr(monitor.db, "quote_for", lambda symbol: quote if symbol == "SPY" else None)
    monkeypatch.setattr(monitor.db, "get_metric", lambda key: values.get(key))
    monkeypatch.setattr(
        monitor.db, "set_metric",
        lambda key, value: values.__setitem__(key, SimpleNamespace(value=value)),
    )

    import asyncio
    alerts = asyncio.run(monitor.scan_portfolio_signal_changes())
    assert len(alerts) == 1
    assert "SPY" in alerts[0]
    assert "+4.00%" in alerts[0]
    assert "no constituye una señal" in alerts[0]
