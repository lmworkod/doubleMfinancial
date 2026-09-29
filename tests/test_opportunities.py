from datetime import UTC, datetime, timedelta

import numpy as np

from app.opportunities import evaluate_history


def _history(now: datetime, count: int = 100, *, latest_age: int = 0) -> list[tuple[datetime, float]]:
    """Build deterministic daily observations ending at the requested age."""
    end = now - timedelta(days=latest_age)
    return [
        (end - timedelta(days=count - 1 - i), 100.0 + i)
        for i in range(count)
    ]


def test_opportunity_requires_sufficient_history():
    now = datetime(2026, 9, 29, tzinfo=UTC)
    rows = _history(now, count=MIN_HISTORY - 1) if False else _history(now, count=63)
    assert evaluate_history("SPY", rows, now) is None


def test_opportunity_accepts_minimum_history():
    now = datetime(2026, 9, 29, tzinfo=UTC)
    result = evaluate_history("SPY", _history(now, count=64), now)
    assert result is not None
    assert result.price == 163.0


def test_opportunity_excludes_stale_history():
    now = datetime(2026, 9, 29, tzinfo=UTC)
    rows = _history(now, count=100, latest_age=8)
    assert evaluate_history("SPY", rows, now) is None


def test_opportunity_calculates_technical_metrics():
    now = datetime(2026, 9, 29, tzinfo=UTC)
    prices = np.linspace(100, 160, 220)
    rows = [(now - timedelta(days=219-i), float(price)) for i, price in enumerate(prices)]
    result = evaluate_history("SPY", rows, now)
    assert result is not None
    assert result.momentum_21d > 0
    assert result.momentum_63d > 0
    assert result.volatility_20d >= 0
    assert result.trend == "alcista"
    assert 0 <= result.score <= 100


def test_opportunity_ignores_invalid_prices():
    now = datetime(2026, 9, 29, tzinfo=UTC)
    rows = _history(now, count=100)
    rows[-1] = (rows[-1][0], float("nan"))
    result = evaluate_history("SPY", rows, now)
    assert result is not None
    assert result.price == 198.0
    assert result.observed_at == rows[-2][0]
