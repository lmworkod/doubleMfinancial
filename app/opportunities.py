"""Transparent swing-horizon opportunity screening (1–3 months).

This technical screen is not a return forecast or trade instruction. The
discovery universe is explicit and limited; missing/stale history is excluded.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape

import numpy as np

from app import db
from app.instruments import INSTRUMENTS

logger = logging.getLogger(__name__)

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


def _signal(item: Opportunity) -> tuple[str, str]:
    """Return a descriptive directional label from trend and momentum."""
    if item.trend == "alcista" and item.momentum_21d > 0 and item.momentum_63d > 0:
        return "🟢 Sesgo comprador", "buy"
    if item.momentum_21d < 0 and item.momentum_63d < 0 and item.score < 50:
        return "🔴 Sesgo vendedor", "sell"
    return "🟡 Neutral · señales mixtas", "neutral"


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
    watchlist = {symbol.upper() for symbol in db.get_watchlist_symbols()}
    discovery = set(DISCOVERY_UNIVERSE) | set(INSTRUMENTS)
    return [
        (symbol, " + ".join(origin for condition, origin in (
            (symbol in holdings, "cartera"), (symbol in watchlist, "watchlist"),
            (symbol in discovery, "exploración"),
        ) if condition))
        for symbol in sorted(holdings | watchlist | discovery)
    ]


def _format_candidate(item: Opportunity) -> list[str]:
    signal, _ = _signal(item)
    origins = set(item.origin.split(" + "))
    overlaps = [label for key, label in (
        ("cartera", "💼 cartera"), ("watchlist", "👀 watchlist"),
        ("exploración", "🧭 exploración"),
    ) if key in origins]
    return [
        f"\n<b>{escape(item.symbol)}</b> · {signal}",
        f"{escape(item.name)} · índice técnico {item.score:.0f}/100",
        f"🏷️ Origen: {', '.join(overlaps)}",
        f"💵 Cierre: {item.price:,.2f} {item.currency} · {item.observed_at:%Y-%m-%d}",
        f"📈 Momentum: 21 sesiones {item.momentum_21d:+.1%} · 63 sesiones {item.momentum_63d:+.1%}",
        f"🌊 Volatilidad anualizada (20 sesiones): {item.volatility_20d:.1%}",
        f"📉 Drawdown desde máximo de 126 sesiones: {item.drawdown_126d:.1%} · Tendencia: {item.trend}",
        "🔍 Evidencia: " + ("; ".join(escape(x) for x in item.evidence) or "sin condiciones positivas destacadas"),
    ]


async def build_opportunities_report(services, now: datetime | None = None) -> list[str]:
    """Show only operational signals; none are enabled before out-of-sample validation."""
    now = _aware(now or datetime.now(UTC))
    universe = _source_universe()
    evaluated = 0
    excluded = []
    for symbol, _origin in universe:
        try:
            rows, error = await services.daily_history(symbol, outputsize=220)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not fetch history for %s: %s", symbol, exc)
            excluded.append((symbol, str(exc)[:120]))
            continue
        if rows and evaluate_history(symbol, rows, now) is not None:
            evaluated += 1
        else:
            excluded.append((symbol, error or "histórico insuficiente o desactualizado"))
    lines = [
        "🔎 <b>OPORTUNIDADES · SWING 1–3 MESES</b>",
        "",
        "⏸️ <b>SIN SEÑALES DE ACTUACIÓN VALIDADAS</b>",
        ("El sistema no emite órdenes de compra, aumento, reducción o venta: "
         "las señales técnicas actuales no cuentan con validación predictiva fuera de muestra "
         "ni una confianza calibrada."),
        "",
        (f"📊 Cobertura: {evaluated}/{len(universe)} activos evaluables · "
         f"{now.astimezone().strftime('%d/%m/%Y %H:%M %Z')}"),
        "Las alertas informativas de mercado se gestionan por separado y no implican operar.",
    ]
    if excluded:
        lines.extend(["", f"⚠️ Datos no evaluables: {len(excluded)}"])
        lines.extend(f"• {escape(symbol)}: {escape(reason)}" for symbol, reason in excluded[:8])
        if len(excluded) > 8:
            lines.append(f"• y {len(excluded) - 8} activos más")
    return ["\n".join(lines)]
