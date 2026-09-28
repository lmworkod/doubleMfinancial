import math

import pandas as pd


def risk_features(frame: pd.DataFrame) -> dict[str, float | None]:
    """Descriptive features from daily data. Missing history stays null."""
    if "close" not in frame or frame["close"].dropna().empty:
        return {}
    close = pd.to_numeric(frame["close"], errors="coerce").dropna()
    returns = close.pct_change().dropna()
    latest = float(close.iloc[-1])
    result: dict[str, float | None] = {
        "close": latest,
        "return_20d": float(latest / close.iloc[-21] - 1) if len(close) >= 21 else None,
        "realized_vol_20d": float(returns.tail(20).std(ddof=1) * math.sqrt(252))
            if len(returns) >= 20 else None,
        "drawdown_252d": float(latest / close.tail(252).max() - 1) if len(close) >= 2 else None,
    }
    for column in ("vix", "vix3m", "dspx", "cor1m", "cor6m"):
        values = pd.to_numeric(frame[column], errors="coerce").dropna() if column in frame else pd.Series(dtype=float)
        result[column] = float(values.iloc[-1]) if not values.empty else None
    result["term_structure"] = (float(result["vix3m"] / result["vix"])
        if result["vix"] is not None and result["vix3m"] is not None and result["vix"] != 0 else None)
    return result


def logistic_probability(features: dict[str, float], coefficients: dict[str, float],
                          intercept: float) -> float:
    """Evaluate fitted coefficients only; this function does not train a model."""
    z = intercept + sum(coefficients.get(key, 0.0) * value for key, value in features.items())
    return 1.0 / (1.0 + math.exp(-max(-35.0, min(35.0, z))))


def probability_status(has_trained_model: bool, has_features: bool) -> str:
    if not has_features:
        return "insufficient_data"
    return "available" if has_trained_model else "not_calibrated"
