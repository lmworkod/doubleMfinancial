from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

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


def test_walk_forward_calibration_requires_sufficient_history():
    from app.risk import calibrate_binary_walk_forward

    frame = pd.DataFrame({"x": [0.0, 1.0, 0.5], "target": [0, 1, 0]})
    result = calibrate_binary_walk_forward(frame, ["x"], "target")
    assert result.status == "insufficient_data"
    assert result.brier_score is None


def test_walk_forward_calibration_uses_chronological_holdout():
    from app.risk import calibrate_binary_walk_forward

    # Alternating regimes/classes make both chronological partitions testable.
    n = 500
    x = [float(i % 7) for i in range(n)]
    y = [int((i // 7) % 2) for i in range(n)]
    frame = pd.DataFrame({"x": x, "target": y})
    result = calibrate_binary_walk_forward(
        frame, ["x"], "target", minimum_train=200, minimum_test=50
    )
    assert result.status == "evaluated_not_approved"
    assert result.n_train + result.n_test == n
    assert result.brier_score is not None
    assert 0 <= result.brier_score <= 1
    assert result.log_loss is not None
    assert 0 <= result.calibration_error <= 1
    assert set(result.coefficients) == {"x"}


def test_walk_forward_calibration_rejects_non_binary_labels():
    from app.risk import calibrate_binary_walk_forward

    frame = pd.DataFrame({"x": [float(i) for i in range(400)],
                          "target": [0, 1, 2, 0] * 100})
    with pytest.raises(ValueError, match="binary"):
        calibrate_binary_walk_forward(frame, ["x"], "target",
                                      minimum_train=200, minimum_test=50)
