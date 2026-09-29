from datetime import UTC, datetime, timedelta

import numpy as np

from app.opportunities import evaluate_history


def test_opportunity_requires_sufficient_history():
    now = datetime(2026, 9, 29, tzinfo=UTC)
    rows = [(now - timedelta(days=30-i), 100+i) for i in range(30)]
    result = evaluate_history("SPY", rows, now)
    assert result is not None
    assert result.price == 100.0


def test_opportunity_excludes_stale_history():
    now = datetime(2026, 9, 29, tzinfo=UTC)
    rows = [(now - timedelta(days=100-i), 100+i) for i in range(100)]
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
    rows = [(now - timedelta(days=99-i), 100.0) for i in range(100)]
    rows[-1] = (rows[-1][0], float("nan"))
    assert evaluate_history("SPY", rows, now) is None
