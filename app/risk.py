"""Descriptive, non-predictive risk diagnostics for the current portfolio.

The diagnostics report data quality and cost-relative P/L only. They do not
estimate future returns, issue sell instructions, or imply model calibration.
"""
from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

import pandas as pd


@dataclass(frozen=True)
class RiskObservation:
    symbol: str
    price: float | None
    currency: str
    observed_at: datetime | None
    source: str | None
    average_cost: float | None = None


@dataclass(frozen=True)
class RiskFinding:
    level: str
    label: str
    detail: str


@dataclass(frozen=True)
class AssetRisk:
    symbol: str
    level: str
    findings: tuple[RiskFinding, ...]
    price_age_hours: float | None
    pnl_pct: float | None


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
        values = (
            pd.to_numeric(frame[column], errors="coerce").dropna()
            if column in frame else pd.Series(dtype=float)
        )
        result[column] = float(values.iloc[-1]) if not values.empty else None
    result["term_structure"] = (
        float(result["vix3m"] / result["vix"])
        if result["vix"] is not None and result["vix3m"] is not None
        and result["vix"] != 0 else None
    )
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


def _age_hours(observed_at: datetime | None, now: datetime) -> float | None:
    if observed_at is None:
        return None
    observed = observed_at.replace(tzinfo=UTC) if observed_at.tzinfo is None else observed_at
    current = now.replace(tzinfo=UTC) if now.tzinfo is None else now
    return max(
        0.0,
        (current.astimezone(UTC) - observed.astimezone(UTC)).total_seconds() / 3600,
    )


def assess_asset(observation: RiskObservation, now: datetime | None = None) -> AssetRisk:
    """Assess observable data quality and cost-relative P/L, without prediction."""
    now = now or datetime.now(UTC)
    age = _age_hours(observation.observed_at, now)
    findings: list[RiskFinding] = []
    price_valid = (
        observation.price is not None
        and math.isfinite(observation.price)
        and observation.price > 0
    )
    if not price_valid:
        findings.append(RiskFinding(
            "critical", "Precio no disponible",
            "No es posible evaluar la posición con una cotización válida.",
        ))
    elif age is None:
        findings.append(RiskFinding(
            "warning", "Fecha de cotización desconocida",
            "No se puede verificar la vigencia del precio.",
        ))
    elif age > 168:
        findings.append(RiskFinding(
            "critical", "Cotización muy antigua",
            f"La observación tiene {age:.1f} horas; no debe interpretarse como precio actual.",
        ))
    elif age > 72:
        findings.append(RiskFinding(
            "warning", "Cotización antigua",
            f"La observación tiene {age:.1f} horas; conviene actualizarla antes de valorar el riesgo.",
        ))

    pnl_pct = None
    if price_valid and observation.average_cost is not None:
        if math.isfinite(observation.average_cost) and observation.average_cost > 0:
            pnl_pct = observation.price / observation.average_cost - 1
        else:
            findings.append(RiskFinding(
                "warning", "Coste medio inválido",
                "No se puede calcular el rendimiento frente al coste registrado.",
            ))

    if not findings:
        findings.append(RiskFinding(
            "info", "Sin incidencias observables",
            "No hay indicadores históricos suficientes para estimar riesgo predictivo.",
        ))
    rank = {"info": 0, "warning": 1, "critical": 2}
    level = max((finding.level for finding in findings), key=rank.__getitem__)
    return AssetRisk(observation.symbol, level, tuple(findings), age, pnl_pct)


def portfolio_risk_report(
    observations: Iterable[RiskObservation], now: datetime | None = None
) -> list[AssetRisk]:
    """Return per-holding quality diagnostics; no correlation is assumed."""
    return [assess_asset(item, now) for item in observations]


@dataclass(frozen=True)
class CalibrationReport:
    """Chronological out-of-sample diagnostics for a binary event model."""
    status: str
    n_train: int
    n_test: int
    brier_score: float | None
    log_loss: float | None
    prevalence: float | None
    mean_predicted_probability: float | None
    calibration_error: float | None
    coefficients: dict[str, float] | None
    intercept: float | None


def calibrate_binary_walk_forward(
    frame: pd.DataFrame,
    feature_columns: list[str],
    target_column: str,
    test_fraction: float = 0.25,
    minimum_train: int = 252,
    minimum_test: int = 60,
) -> CalibrationReport:
    """Fit a regularized logistic model on the past and evaluate on a later holdout.

    The caller must provide a chronologically ordered dataset with labels whose
    horizons do not overlap across the train/test boundary. This function refuses
    undersized, non-finite, single-class or malformed samples and never claims
    a model is validated from in-sample fit quality.
    """
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import brier_score_loss, log_loss

    empty = CalibrationReport("insufficient_data", 0, 0, None, None, None,
                              None, None, None, None)
    if not feature_columns or target_column not in frame:
        return empty
    if not 0 < test_fraction < 0.5:
        raise ValueError("test_fraction must be between 0 and 0.5")
    data = frame[feature_columns + [target_column]].copy()
    data = data.replace([float("inf"), float("-inf")], float("nan")).dropna()
    if len(data) < minimum_train + minimum_test:
        return empty
    y = data[target_column]
    if not y.isin([0, 1, False, True]).all():
        raise ValueError("target must contain only binary 0/1 labels")
    # Purge the 20 observations before the holdout: forward 20-session labels
    # must not share outcome windows across the train/test boundary.
    split = max(minimum_train + 20, int(len(data) * (1 - test_fraction)))
    train, test = data.iloc[:split - 20], data.iloc[split:]
    if len(train) < minimum_train or len(test) < minimum_test:
        return empty
    if train[target_column].nunique() < 2 or test[target_column].nunique() < 2:
        return CalibrationReport("insufficient_class_diversity", len(train), len(test),
                                 None, None, None, None, None, None, None)
    model = LogisticRegression(C=1.0, class_weight=None, max_iter=2000,
                               solver="lbfgs")
    model.fit(train[feature_columns].astype(float), train[target_column].astype(int))
    probabilities = model.predict_proba(test[feature_columns].astype(float))[:, 1]
    actual = test[target_column].astype(int).to_numpy()
    brier = float(brier_score_loss(actual, probabilities))
    loss = float(log_loss(actual, probabilities, labels=[0, 1]))
    # Expected calibration error over ten fixed probability bins.
    edges = [i / 10 for i in range(11)]
    ece = 0.0
    for i in range(10):
        mask = ((probabilities >= edges[i]) &
                (probabilities < edges[i + 1] if i < 9 else probabilities <= edges[i + 1]))
        if mask.any():
            ece += float(mask.mean()) * abs(float(actual[mask].mean()) -
                                            float(probabilities[mask].mean()))
    return CalibrationReport(
        "evaluated_not_approved", len(train), len(test), brier, loss,
        float(actual.mean()), float(probabilities.mean()), float(ece),
        {name: float(value) for name, value in zip(feature_columns, model.coef_[0])},
        float(model.intercept_[0]),
    )
