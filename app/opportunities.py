"""Transparent swing-horizon opportunity screening (1–3 months).

This technical screen is not a return forecast or trade instruction. The
discovery universe is explicit and limited; missing/stale history is excluded.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape

import numpy as np

from app import db
from app.config import settings
from app.instruments import INSTRUMENTS

DISCOVERY_UNIVERSE = ("SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLV", "XLE",
                      "GLD", "SLV", "TLT", "HYG", "EEM", "SMH", "ARKK")
MIN_HISTORY = 64
MAX_HISTORY_AGE_DAYS = 7
MAX_RESULTS = 8


@dataclass(frozen=True)
class Opportunity:
    symbol: str
    name: str
    origin: str
    price: float
    currency: str
    observed_at: datetime
    momentum_63d: float
    momentum_21d: float
    volatility_20d: float
    drawdown_126d: float
    trend: str
    evidence: tuple[str, ...]
    score: float


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def evaluate_history(symbol: str, rows: list[tuple[datetime, float]],
                     now: datetime | None = None) -> Opportunity | None:
    """Compute a transparent descriptive score; it is not a probability."""
    now = _aware(now or datetime.now(UTC))
    clean = []
    for observed, raw in rows:
        try:
            price = float(raw)
        except (TypeError, ValueError):
            continue
        if np.isfinite(price) and price > 0:
            clean.append((_aware(observed), price))
    unique = {dt.date(): (dt, price) for dt, price in clean}
    history = sorted(unique.values(), key=lambda item: item[0])
    if len(history) < MIN_HISTORY:
        return None
    if (now.date() - history[-1][0].date()).days > MAX_HISTORY_AGE_DAYS:
        return None
    closes = np.asarray([price for _, price in history], dtype=float)
    returns = np.diff(np.log(closes))
    latest = float(closes[-1])
    mom21 = latest / float(closes[-22]) - 1
    mom63 = latest / float(closes[-64]) - 1
    ma50 = float(np.mean(closes[-50:]))
    ma200 = float(np.mean(closes[-200:])) if len(closes) >= 200 else None
    volatility = float(np.std(returns[-20:], ddof=1) * np.sqrt(252))
    drawdown = latest / float(np.max(closes[-126:])) - 1
    if not np.isfinite(volatility):
        return None
    trend = "alcista" if latest > ma50 and (ma200 is None or ma50 > ma200) else "mixta"
    evidence = []
    if latest > ma50:
        evidence.append("precio por encima de media de 50 sesiones")
    if ma200 is not None and ma50 > ma200:
        evidence.append("media de 50 por encima de media de 200")
    if mom63 > 0:
        evidence.append(f"momentum 63 sesiones {mom63:+.1%}")
    if mom21 > 0:
        evidence.append(f"momentum 21 sesiones {mom21:+.1%}")
    if drawdown <= -0.10:
        evidence.append(f"drawdown desde máximo de 126 sesiones {drawdown:.1%}")
    score = (25 * (latest > ma50) + 25 * (ma200 is not None and ma50 > ma200)
             + 25 * (mom63 > 0) + 15 * (mom21 > 0) + 10 * (drawdown > -0.10))
    return Opportunity(
        symbol=symbol, name=INSTRUMENTS[symbol].name if symbol in INSTRUMENTS else symbol,
        origin="", price=latest,
        currency=INSTRUMENTS[symbol].quote_currency if symbol in INSTRUMENTS else "USD",
        observed_at=history[-1][0], momentum_63d=mom63, momentum_21d=mom21,
        volatility_20d=volatility, drawdown_126d=drawdown, trend=trend,
        evidence=tuple(evidence), score=float(score),
    )


def _source_universe() -> list[tuple[str, str]]:
    holdings = {item.symbol.upper() for item in db.get_holdings()}
    watchlist = set(settings.symbols)
    discovery = set(DISCOVERY_UNIVERSE) | set(INSTRUMENTS)
    return [
        (symbol, " + ".join(origin for condition, origin in (
            (symbol in holdings, "cartera"), (symbol in watchlist, "watchlist"),
            (symbol in discovery, "exploración"),
        ) if condition))
        for symbol in sorted(holdings | watchlist | discovery)
    ]


async def build_opportunities_report(services, now: datetime | None = None) -> list[str]:
    now = _aware(now or datetime.now(UTC))
    universe = _source_universe()
    candidates, excluded = [], []
    for symbol, origin in universe:
        rows, error = await services.daily_history(symbol, outputsize=220)
        if not rows:
            excluded.append((symbol, error or "histórico no disponible"))
            continue
        item = evaluate_history(symbol, rows, now)
        if item is None:
            excluded.append((symbol, "histórico insuficiente o desactualizado"))
            continue
        candidates.append(Opportunity(**{**item.__dict__, "origin": origin}))
    candidates.sort(key=lambda item: item.symbol)
    lines = [
        "🔎 <b>OPORTUNIDADES · SWING</b> · 1–3 meses",
        f"Universo: {len(universe)} activos · Evaluables: {len(candidates)} · {now.astimezone().strftime('%d/%m/%Y %H:%M %Z')}",
        "",
    ]
    if not candidates:
        lines.extend(["No hay activos con histórico diario suficiente y reciente.",
                      "Los activos sin datos válidos se excluyen; no se imputan precios."])
    else:
        lines.append("<b>Cribado técnico</b>")
        for item in candidates[:MAX_RESULTS]:
            lines.extend([
                f"\n<b>{escape(item.symbol)}</b> · índice técnico {item.score:.0f}/100",
                f"{escape(item.name)} · {escape(item.origin)}",
                f"Cierre: {item.price:,.2f} {item.currency} · {item.observed_at:%Y-%m-%d}",
                f"Momentum: 21 sesiones {item.momentum_21d:+.1%} · 63 sesiones {item.momentum_63d:+.1%}",
                f"Volatilidad realizada anualizada (20 sesiones): {item.volatility_20d:.1%}",
                f"Drawdown desde máximo de 126 sesiones: {item.drawdown_126d:.1%} · Tendencia: {item.trend}",
                "Evidencia: " + ("; ".join(escape(x) for x in item.evidence) or "sin condiciones positivas destacadas"),
            ])
    if excluded:
        lines.extend(["", f"<b>Cobertura</b> · {len(excluded)} activos excluidos por datos no disponibles"])
        lines.extend(f"• {escape(symbol)}: {escape(reason)}" for symbol, reason in excluded[:8])
        if len(excluded) > 8:
            lines.append(f"• y {len(excluded) - 8} activos más")
    lines.extend([
        "",
        "<i>El índice 0–100 resume condiciones técnicas observadas; no es una probabilidad, una rentabilidad esperada ni una recomendación. El universo de exploración es una lista explícita de ETF, no un screener exhaustivo. No se incorporan fundamentales, costes ni liquidez.</i>",
    ])
    chunks, current, size = [], [], 0
    for line in lines:
        increment = len(line) + (1 if current else 0)
        if size + increment > 3800 and current:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += increment
    if current:
        chunks.append("\n".join(current))
    return chunks
