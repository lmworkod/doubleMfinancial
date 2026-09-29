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
    watchlist = {symbol.upper() for symbol in settings.symbols}
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
    now = _aware(now or datetime.now(UTC))
    universe = _source_universe()
    candidates, excluded = [], []
    for symbol, origin in universe:
        rows, error = await services.daily_history(symbol, outputsize=220)
        if not rows:
            excluded.append((symbol, error or "histórico no disponible", origin))
            continue
        item = evaluate_history(symbol, rows, now)
        if item is None:
            excluded.append((symbol, "histórico insuficiente o desactualizado", origin))
            continue
        candidates.append(Opportunity(**{**item.__dict__, "origin": origin}))

    sections = (
        ("💼 <b>1. CARTERA · POSICIONES ACTUALES</b>", "cartera"),
        ("👀 <b>2. WATCHLIST · ACTIVOS OBSERVADOS</b>", "watchlist"),
        ("🧭 <b>3. EXPLORACIÓN · UNIVERSO AMPLIADO</b>", "exploración"),
    )
    holdings = [item for item in candidates if "cartera" in item.origin.split(" + ")]
    buys = [item for item in holdings if _signal(item)[1] == "buy"]
    sells = [item for item in holdings if _signal(item)[1] == "sell"]
    headline = (f"🧭 <b>HEADLINE: {len(buys)} posiciones con sesgo comprador · "
                f"{len(sells)} con sesgo vendedor · "
                f"{len(holdings) - len(buys) - len(sells)} neutrales</b>"
                if holdings else "🧭 <b>HEADLINE: no hay posiciones evaluables</b>")
    lines = [
        "🔎 <b>OPORTUNIDADES · SWING</b> · 1–3 meses",
        headline,
        f"🌐 Universo: {len(universe)} activos · Evaluables: {len(candidates)} · {now.astimezone().strftime('%d/%m/%Y %H:%M %Z')}",
        "🟢 Sesgo comprador · 🔴 Sesgo vendedor · 🟡 Neutral",
    ]
    for heading, source in sections:
        members = [item for item in candidates if source in item.origin.split(" + ")]
        members.sort(key=lambda item: (_signal(item)[1] == "neutral", -item.score, item.symbol))
        lines.extend(["", heading, f"📊 {len(members)} activos evaluables"])
        if not members:
            lines.append("— Sin activos evaluables en esta sección.")
        else:
            for item in members[:MAX_RESULTS]:
                lines.extend(_format_candidate(item))
            if len(members) > MAX_RESULTS:
                lines.append(f"… y {len(members) - MAX_RESULTS} activos más.")
    if excluded:
        lines.extend(["", f"⚠️ <b>COBERTURA</b> · {len(excluded)} activos excluidos"])
        lines.extend(f"• <b>{escape(symbol)}</b> ({escape(origin)}): {escape(reason)}"
                     for symbol, reason, origin in excluded[:8])
        if len(excluded) > 8:
            lines.append(f"• y {len(excluded) - 8} activos más")
    lines.extend([
        "",
        "<i>El sesgo es una clasificación técnica descriptiva, no una orden ni recomendación de compra o venta. El índice 0–100 no es una probabilidad ni una rentabilidad esperada. El universo de exploración es una lista explícita de ETF, no un screener exhaustivo. No se incorporan fundamentales, costes ni liquidez.</i>",
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
