from datetime import UTC, datetime, timedelta

import pandas as pd

from app.risk import (
    RiskObservation,
    assess_asset,
    logistic_probability,
    probability_status,
    risk_features,
)


def test_features_leave_short_history_undefined():
    result = risk_features(pd.DataFrame({"close": [100, 101, 99]}))
    assert result["close"] == 99.0
    assert result["realized_vol_20d"] is None
    assert result["return_20d"] is None


def test_term_structure_needs_vix_and_vix3m():
    result = risk_features(pd.DataFrame({"close": [100, 101], "vix": [20, 21], "vix3m": [22, 23]}))
    assert result["term_structure"] == 23 / 21


def test_logistic_function_uses_explicit_parameters():
    assert logistic_probability({"x": 1.0}, {"x": 0.0}, 0.0) == 0.5


def test_uncalibrated_model_is_not_misrepresented():
    assert probability_status(False, True) == "not_calibrated"
    assert probability_status(False, False) == "insufficient_data"


def test_stale_quote_is_flagged_and_never_called_current():
    now = datetime(2026, 9, 28, 12, tzinfo=UTC)
    result = assess_asset(RiskObservation(
        "SPY", 500.0, "USD", now - timedelta(days=4), "stooq_daily", 450.0
    ), now)
    assert result.level == "warning"
    assert result.pnl_pct == 500 / 450 - 1
    assert result.findings[0].label == "Cotización antigua"


def test_missing_price_is_critical_data_quality_not_sell_signal():
    result = assess_asset(RiskObservation("QQQ", None, "USD", None, None), datetime.now(UTC))
    assert result.level == "critical"
    assert result.findings[0].label == "Precio no disponible"


def test_missing_cost_does_not_fabricate_pnl():
    result = assess_asset(RiskObservation(
        "IWM", 200.0, "USD", datetime.now(UTC), "provider", None
    ))
    assert result.pnl_pct is None
    assert result.level == "info"
