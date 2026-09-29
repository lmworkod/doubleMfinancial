"""Daily portfolio digest formatting for the authorized Telegram owner."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

from app import db
from app.portfolio import holdings_fingerprint, portfolio_snapshot


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def human_age(value: datetime | None, now: datetime) -> str:
    if value is None:
        return "pendiente"
    seconds = max(0, int((_aware(now) - _aware(value)).total_seconds()))
    if seconds < 60:
        return f"hace {seconds} min"
    if seconds < 3600:
        minutes = seconds // 60
        return f"hace {minutes} min"
    if seconds < 86400:
        hours = seconds // 3600
        return f"hace {hours} h"
    days = seconds // 86400
    return f"hace {days} día" if days == 1 else f"hace {days} días"


def _parse_datetime(value: str | None) -> datetime | None:
    if not value or value == "unknown":
        return None
    try:
        return _aware(datetime.fromisoformat(value))
    except ValueError:
        return None


def _pnl_since(total: float, cutoff: datetime, fingerprint: str, now: datetime) -> str:
    baseline = db.portfolio_snapshot_before(cutoff, fingerprint)
    if baseline is None or baseline.coverage < 1.0:
        return "no disponible (histórico comparable insuficiente)"
    # A baseline must be reasonably close to its requested horizon.
    age = cutoff - _aware(baseline.captured_at)
    if age > timedelta(days=2):
        return "no disponible (sin valoración de referencia cercana)"
    return f"{total - baseline.value_eur:+,.2f} EUR"


def _period_change(key: str, current: float | None, period: str,
                   days: int, observed: datetime | None) -> str:
    if current is None or observed is None:
        return f"{period}: —"
    previous = db.metric_history_at_or_before(key, observed - timedelta(days=days))
    if previous is None or previous.value == 0:
        return f"{period}: —"
    change = (current / previous.value - 1) * 100
    return f"{period}: {change:+.2f}%"


def _macro_line(key: str, label: str, now: datetime, periods: tuple[int, int, int]) -> str:
    metric = db.get_metric(f"fred_{key}")
    asof_metric = db.get_metric(f"fred_{key}_as_of")
    value = float(metric.value) if metric else None
    observed = _parse_datetime(asof_metric.value if asof_metric else None)
    age = human_age(metric.observed_at if metric else None, now)
    trends = " · ".join(_period_change(f"fred_{key}", value, name, days, observed)
                        for name, days in zip(("WoW", "MoM", "YoY"), periods))
    shown = f"{value:,.4f}".rstrip("0").rstrip(".") if value is not None else "sin dato"
    return f"• {label}: {shown} · actualizado {age} · {trends}"


def _fx_line(now: datetime, periods: tuple[int, int, int]) -> str:
    metric = db.get_metric("fx_usd_per_eur")
    asof_metric = db.get_metric("fx_usd_per_eur_as_of")
    try:
        value = float(metric.value) if metric else None
    except (TypeError, ValueError):
        value = None
    observed = _parse_datetime(asof_metric.value if asof_metric else None)
    age = human_age(metric.observed_at if metric else None, now)
    trends = " · ".join(_period_change("fx_usd_per_eur", value, name, days, observed)
                        for name, days in zip(("WoW", "MoM", "YoY"), periods))
    shown = f"{value:.4f}" if value is not None else "sin dato"
    return f"• USD/EUR de referencia: {shown} · actualizado {age} · {trends}"


def build_daily_digest(now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    now_utc = _aware(now)
    lines: list[str] = [
        f"📊 DoubleM Financial · Resumen diario ({now.astimezone().strftime('%d/%m/%Y')})"
    ]
    items, total, coverage = portfolio_snapshot()
    if not items:
        lines.extend(["", "Inventario: no hay posiciones registradas."])
    else:
        lines.extend(["", f"💼 Valor conocido: {total:,.2f} EUR",
                      f"Cobertura de valoración: {coverage:.0%}"])
        fingerprint = holdings_fingerprint(items)
        # Save a baseline only when every holding is valued, avoiding partial-total P/L.
        if coverage == 1.0:
            db.record_portfolio_snapshot(total, coverage, fingerprint, now_utc)
        lines.extend([
            f"P/L del día: {_pnl_since(total, now_utc - timedelta(days=1), fingerprint, now_utc)}",
            f"P/L acumulado de la semana: {_pnl_since(total, now_utc - timedelta(days=7), fingerprint, now_utc)}",
            "", "📦 Inventario"
        ])
        for item in items:
            if item.price is None:
                lines.append(f"• ⚪ {item.symbol}: {item.quantity:g} uds. · sin cotización")
                continue
            value = f"{item.market_value:,.2f} EUR" if item.market_value is not None else "valor EUR no disponible"
            if item.pnl is None or abs(item.pnl) < 0.005:
                arrow = "⚪"
            elif item.pnl > 0:
                arrow = "🟢⬆️"
            else:
                arrow = "🔴⬇️"
            pnl = f" · P/L desde coste: {item.pnl:+,.2f} EUR" if item.pnl is not None else ""
            lines.append(f"• {arrow} {item.symbol}: {item.quantity:g} × {item.price:,.4f} {item.currency} · {value}{pnl}")
    lines.extend(["", "🌐 Datos macro"])
    for key, label in (("fed_funds", "Fed Funds"), ("ust10y", "Treasury 10Y"),
                       ("usd_broad", "USD broad")):
        lines.append(_macro_line(key, label, now_utc, (7, 30, 365)))
    lines.append(_fx_line(now_utc, (7, 30, 365)))
    market_refresh, macro_refresh = db.get_metric("last_quote_refresh"), db.get_metric("last_macro_refresh")
    market_at = _parse_datetime(market_refresh.value if market_refresh else None)
    macro_at = _parse_datetime(macro_refresh.value if macro_refresh else None)
    lines.extend(["", "🕒 Últimas consultas",
                  f"• Mercado: {human_age(market_at, now_utc)}",
                  f"• Macro: {human_age(macro_at, now_utc)}",
                  "", "Los cierres diarios pueden corresponder al último día hábil. Las cotizaciones fallidas conservan el último valor válido; comprueba su antigüedad antes de interpretar la valoración. El P/L usa el tipo FX actual, no el histórico. No incluye efectivo ni comisiones. El SP500-VRM permanece sin probabilidades operativas hasta completar calibración y validación fuera de muestra."])
    return "\n".join(lines)
