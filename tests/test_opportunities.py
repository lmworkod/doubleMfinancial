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
    rows = _history(now, count=63)
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


from app.opportunities import Opportunity, _format_candidate, _signal


def _candidate(*, origin: str = "cartera", trend: str = "alcista",
               momentum_21d: float = 0.05, momentum_63d: float = 0.10,
               score: float = 80) -> Opportunity:
    return Opportunity(
        symbol="SPY", name="SPDR S&P 500", origin=origin, price=500.0,
        currency="USD", observed_at=datetime(2026, 9, 29, tzinfo=UTC),
        momentum_63d=momentum_63d, momentum_21d=momentum_21d,
        volatility_20d=0.15, drawdown_126d=-0.02, trend=trend,
        evidence=("momentum positivo",), score=score,
    )


def test_signal_classifies_positive_trend_as_buying_bias():
    assert _signal(_candidate()) == ("🟢 Sesgo comprador", "buy")


def test_signal_classifies_negative_momentum_as_selling_bias():
    item = _candidate(trend="mixta", momentum_21d=-0.05,
                      momentum_63d=-0.10, score=30)
    assert _signal(item) == ("🔴 Sesgo vendedor", "sell")


def test_signal_keeps_mixed_conditions_neutral():
    item = _candidate(momentum_21d=-0.01, momentum_63d=0.10)
    assert _signal(item) == ("🟡 Neutral · señales mixtas", "neutral")


def test_candidate_format_shows_all_origins_and_emojis():
    lines = _format_candidate(_candidate(origin="cartera + watchlist + exploración"))
    report = "\\n".join(lines)
    assert "💼 cartera" in report
    assert "👀 watchlist" in report
    assert "🧭 exploración" in report
    assert "📈 Momentum" in report
