import pandas as pd

from app.risk import logistic_probability, probability_status, risk_features


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
